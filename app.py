import os
from urllib.parse import urlparse
import joblib
import numpy as np
import pandas as pd
import pymysql
import pymysql.cursors
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# ==========================================
# 1. Configuration & Model Loading
# ==========================================
MODEL_PATH = "random_forest_air_quality.pkl"
try:
    rf_model = joblib.load(MODEL_PATH)
    print("✅ Random Forest model loaded successfully!")
except Exception as e:
    print(f"❌ Error loading model: {e}")
    rf_model = None

# Railway Environment Variables
DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SENSOR_COLS = ["co2", "pm25", "pm10", "temperature", "humidity", "is_valid"]
LAGS = [0, 5, 10, 15]


def get_db_connection():
    """Connects to the Railway MySQL database using DATABASE_URL."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set.")

    db_url = urlparse(DATABASE_URL)
    return pymysql.connect(
        host=db_url.hostname,
        user=db_url.username,
        password=db_url.password,
        database=db_url.path.lstrip("/"),
        port=db_url.port or 3306,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


# ==========================================
# 2. Telegram Alert Function
# ==========================================
def check_and_send_telegram_alert(pred_pm25, pred_pm10, pred_co2):
    """Sends a Telegram alert if predicted 15-min levels breach safety limits."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    alerts = []
    if pred_pm25 > 35.0:
        alerts.append(f"• *PM2.5* predicted at `{pred_pm25:.1f} µg/m³` (Unhealthy)")
    if pred_pm10 > 100.0:
        alerts.append(f"• *PM10* predicted at `{pred_pm10:.1f} µg/m³` (Elevated)")
    if pred_co2 > 1000.0:
        alerts.append(f"• *CO2* predicted at `{pred_co2:.0f} ppm` (Poor Ventilation)")

    if alerts:
        message = (
            "⚠️ *15-MINUTE AIR QUALITY WARNING* ⚠️\n\n"
            "Forecast predicts thresholds will be exceeded:\n"
            + "\n".join(alerts)
            + "\n\n💡 *Recommendation:* Please turn on ventilation or air purifiers."
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            requests.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "Markdown",
                },
                timeout=5,
            )
        except Exception as e:
            print(f"Telegram notification error: {e}")


# ==========================================
# 3. Feature Vector Builder
# ==========================================
def build_features_from_history(recent_rows, current_reading):
    """Combines previous MySQL rows with the live incoming reading

    to construct the 24 lag features for the Random Forest model.
    """
    all_readings = recent_rows + [current_reading]
    df = pd.DataFrame(all_readings)
    df.columns = df.columns.str.strip().str.lower()

    feature_dict = {}
    for col in SENSOR_COLS:
        for lag in LAGS:
            if lag == 0:
                feature_dict[f"{col}_current"] = df[col].iloc[-1]
            else:
                feature_dict[f"{col}_lag_{lag}"] = df[col].iloc[-1 - lag]

    return pd.DataFrame([feature_dict])


# ==========================================
# 4. Main Ingestion Endpoint (ESP32 / Postman -> Server)
# ==========================================
@app.route("/api/sensor-data", methods=["POST"])
def ingest_sensor_data():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"}), 400

    current_reading = {
        "co2": float(data.get("co2", 0)),
        "pm25": float(data.get("pm25", 0)),
        "pm10": float(data.get("pm10", 0)),
        "temperature": float(data.get("temperature", 0)),
        "humidity": float(data.get("humidity", 0)),
        "is_valid": int(data.get("is_valid", 1)),
    }

    pred_pm25, pred_pm10, pred_co2 = None, None, None

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Step A: Query past 15 records from MySQL table
            cur.execute(
                """
                SELECT co2, pm25, pm10, temperature, humidity, is_valid 
                FROM sensor_logs 
                ORDER BY timestamp DESC 
                LIMIT 15
            """
            )
            recent_history = cur.fetchall()
            recent_history.reverse()

            # Step B: Predict if enough history is available
            if len(recent_history) >= 15 and rf_model is not None:
                features_df = build_features_from_history(
                    recent_history, current_reading
                )
                predictions = rf_model.predict(features_df)[0]

                pred_pm25 = round(float(predictions[0]), 2)
                pred_pm10 = round(float(predictions[1]), 2)
                pred_co2 = round(float(predictions[2]), 2)

                # Step C: Send Telegram alert if necessary
                check_and_send_telegram_alert(pred_pm25, pred_pm10, pred_co2)

            # Step D: Insert current readings and forecast into MySQL
            cur.execute(
                """
                INSERT INTO sensor_logs 
                (co2, pm25, pm10, temperature, humidity, is_valid, pred_pm25, pred_pm10, pred_co2, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
                (
                    current_reading["co2"],
                    current_reading["pm25"],
                    current_reading["pm10"],
                    current_reading["temperature"],
                    current_reading["humidity"],
                    current_reading["is_valid"],
                    pred_pm25,
                    pred_pm10,
                    pred_co2,
                ),
            )

        conn.close()

        return (
            jsonify(
                {
                    "status": "success",
                    "current": current_reading,
                    "prediction_15min": {
                        "pm25": pred_pm25,
                        "pm10": pred_pm10,
                        "co2": pred_co2,
                    },
                }
            ),
            201,
        )

    except Exception as e:
        print(f"Error during ingestion: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "running", "service": "Air Quality Predictor"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

