import json
import os
import time
from urllib.parse import urlparse
from google import genai
import joblib
import numpy as np
import pandas as pd
import pymysql
import pymysql.cursors
import requests
from flask import Flask, jsonify, render_template, request

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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini AI Client
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SENSOR_COLS = ["co2", "pm25", "pm10", "temperature", "humidity", "is_valid"]
LAGS = [0, 5, 10, 15]

# In-memory AI advice cache
cached_ai_response = {
    "status_badge": "Optimal",
    "analysis": "Air quality is currently stable and within healthy thresholds.",
    "action": "Air quality is optimal. No action required.",
    "last_updated": 0,
}


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
    if pred_pm25 and pred_pm25 > 35.0:
        alerts.append(f"• *PM2.5* predicted at `{pred_pm25:.1f} µg/m³` (Unhealthy)")
    if pred_pm10 and pred_pm10 > 100.0:
        alerts.append(f"• *PM10* predicted at `{pred_pm10:.1f} µg/m³` (Elevated)")
    if pred_co2 and pred_co2 > 1000.0:
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
# 3. Dynamic Gemini AI Copilot
# ==========================================
def generate_ai_recommendation(current, pred_pm25, pred_pm10, pred_co2):
    """Uses Gemini to generate real-time, context-aware indoor air advice."""
    global cached_ai_response

    # Reuse cached advice for 2 minutes (120s) to keep page loading instantaneous
    if time.time() - cached_ai_response.get("last_updated", 0) < 120:
        return cached_ai_response

    if not ai_client:
        is_bad = (pred_pm25 and pred_pm25 > 35) or (pred_co2 and pred_co2 > 1000)
        return {
            "status_badge": "Alert" if is_bad else "Optimal",
            "analysis": "Telemetry monitored. Add GEMINI_API_KEY in Railway Variables for full AI advice.",
            "action": "Open windows for ventilation or run air purifier." if is_bad else "Conditions are normal.",
            "last_updated": time.time(),
        }

    prompt = f"""
    You are an expert Indoor Environmental Quality AI Copilot for a smart building IoT system.
    Analyze this telemetry data:
    - Current Readings: PM2.5: {current.get('pm25', 0)} ug/m3, PM10: {current.get('pm10', 0)} ug/m3, CO2: {current.get('co2', 0)} ppm, Temp: {current.get('temperature', 0)}°C, Humidity: {current.get('humidity', 0)}%
    - 15-Minute ML Forecast: Predicted PM2.5: {pred_pm25} ug/m3, Predicted PM10: {pred_pm10} ug/m3, Predicted CO2: {pred_co2} ppm

    Provide a concise assessment in exactly this JSON format (no markdown code blocks, just raw JSON):
    {{
      "status_badge": "Safe" or "Moderate" or "Danger Warning",
      "analysis": "A 1-2 sentence technical summary explaining what is happening or forecasted to happen based on temperature, humidity, CO2 and particulate levels.",
      "action": "A specific, actionable instruction for the occupant (e.g., open windows, turn on HEPA purifier, adjust AC, turn on exhaust fan)."
    }}
    """

    try:
        response = ai_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
        )
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        ai_data = json.loads(clean_text)
        ai_data["last_updated"] = time.time()
        cached_ai_response = ai_data
        return ai_data
    except Exception as e:
        print(f"AI Generation Error: {e}")
        return cached_ai_response


# ==========================================
# 4. Feature Vector Builder
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
# 5. Routes
# ==========================================

# 5.1 Render HTML Dashboard
@app.route("/", methods=["GET"])
def dashboard():
    return render_template("index.html")


# 5.2 Sensor Data Ingestion (ESP32 -> Railway DB -> Prediction)
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
            cur.execute(
                """
                SELECT id, timestamp, co2, pm25, pm10, temperature, humidity,
                    pred_pm25, pred_pm10, pred_co2
                FROM sensor_logs
                ORDER BY timestamp DESC
                LIMIT 5000
            """
            )
            raw_history = cur.fetchall()
            recent_history = list(raw_history)[::-1] if raw_history else []

            # Predict if enough history is available
            if len(recent_history) >= 15 and rf_model is not None:
                features_df = build_features_from_history(
                    recent_history, current_reading
                )
                predictions = rf_model.predict(features_df)[0]

                pred_pm25 = round(float(predictions[0]), 2)
                pred_pm10 = round(float(predictions[1]), 2)
                pred_co2 = round(float(predictions[2]), 2)

                # Send Telegram alert if necessary
                check_and_send_telegram_alert(pred_pm25, pred_pm10, pred_co2)

            # Insert current readings and forecast into MySQL
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


# 5.3 Dashboard Telemetry & AI Advice Feed
@app.route("/api/dashboard-data", methods=["GET"])
def get_dashboard_data():
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, timestamp, co2, pm25, pm10, temperature, humidity,
                       pred_pm25, pred_pm10, pred_co2
                FROM sensor_logs
                ORDER BY timestamp DESC
                LIMIT 30
            """
            )
            raw_rows = cur.fetchall()
        conn.close()

        rows = list(raw_rows)[::-1] if raw_rows else []
        latest = rows[-1] if rows else {}

        # Generate contextual AI Copilot advice
        ai_advice = generate_ai_recommendation(
            current={
                "pm25": latest.get("pm25", 0),
                "pm10": latest.get("pm10", 0),
                "co2": latest.get("co2", 0),
                "temperature": latest.get("temperature", 0),
                "humidity": latest.get("humidity", 0),
            },
            pred_pm25=latest.get("pred_pm25", 0),
            pred_pm10=latest.get("pred_pm10", 0),
            pred_co2=latest.get("pred_co2", 0),
        )

        return (
            jsonify(
                {"status": "success", "data": rows, "ai_advice": ai_advice}
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
