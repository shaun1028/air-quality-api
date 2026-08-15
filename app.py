import joblib
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request

app = Flask(__name__)

# 1. Load the pre-trained Random Forest model when the server boots
MODEL_PATH = "random_forest_air_quality.pkl"
try:
    rf_model = joblib.load(MODEL_PATH)
    print("✅ Random Forest model loaded successfully!")
except Exception as e:
    print(f"❌ Error loading model: {e}")
    rf_model = None

# Define exact feature order expected by the trained model
SENSOR_COLS = ["co2", "pm25", "pm10", "temperature", "humidity", "is_valid"]
LAGS = [0, 5, 10, 15]


def construct_feature_vector(recent_logs):
    """Expects a pandas DataFrame or list of dicts with at least 16 recent logs

    sorted chronologically (oldest to newest) to extract lags at t, t-5, t-10, t-15.
    """
    df = pd.DataFrame(recent_logs)

    # Clean column headers
    df.columns = df.columns.str.strip().str.lower()

    # Generate current (t=0) and lag features (t-5, t-10, t-15)
    feature_dict = {}
    for col in SENSOR_COLS:
        for lag in LAGS:
            if lag == 0:
                # Latest value (current)
                feature_dict[f"{col}_current"] = df[col].iloc[-1]
            else:
                # Historical values from previous intervals
                feature_dict[f"{col}_lag_{lag}"] = df[col].iloc[-1 - lag]

    return pd.DataFrame([feature_dict])


@app.route("/predict", methods=["POST"])
def predict():
    if rf_model is None:
        return jsonify({"error": "Model file not found or failed to load"}), 500

    try:
        data = request.get_json()

        # Check if incoming payload contains recent sensor logs array
        if "logs" not in data or len(data["logs"]) < 16:
            return (
                jsonify(
                    {
                        "error": "Requires a 'logs' list containing at least 16 chronological sensor readings (t=0 down to t-15)."
                    }
                ),
                400,
            )

        # Build feature vector matching training schema
        features_df = construct_feature_vector(data["logs"])

        # Run prediction
        predictions = rf_model.predict(features_df)[0]

        # Structure response
        response = {
            "status": "success",
            "prediction_horizon": "15_minutes",
            "predictions": {
                "pm25": round(float(predictions[0]), 2),
                "pm10": round(float(predictions[1]), 2),
                "co2": round(float(predictions[2]), 2),
            },
        }
        return jsonify(response), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
