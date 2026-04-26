# Standard Library Imports
import sys
import os
from datetime import datetime
import json

# Third-Party Imports
import requests

# Local Application Imports
from utils import Logger, PostgresConnection

# Accessing environment variables for API key info.
# DB connection is resolved by PostgresConnection.from_env() (DATABASE_URL or
# ANALYTICS_DATABASE_URL) — see jobs/utils/postgres_connection.py.
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

def fetch_wind_data(latitude, longitude, logger):
    """Fetch current wind data from OpenWeather API and extract only numeric values.

    Args:
        latitude (float): Latitude of the location.
        longitude (float): Longitude of the location.
        logger (Logger): The logger instance to log messages.

    Returns:
        dict: A dictionary containing wind speed, wind direction, and wind gust (if available).
    """
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={OPENWEATHER_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Will raise HTTPError for bad responses (4xx, 5xx)
        data = response.json()

        wind_speed = data["wind"]["speed"]  # Speed in meters per second
        wind_direction = data["wind"]["deg"]  # Wind direction in degrees
        wind_gust = data["wind"].get("gust", None)  # Gust speed (optional)

        return {
            "wind_speed": wind_speed,
            "wind_direction": wind_direction,
            "wind_gust": wind_gust if wind_gust is not None else None  # Insert NULL for missing gust data
        }
    except requests.exceptions.RequestException as e:
        logger.log_json("ERROR", "Error fetching wind data", {"error": str(e), "latitude": latitude, "longitude": longitude})
        return None
    except KeyError as e:
        logger.log_json("ERROR", "Missing key in API response", {"error": str(e), "latitude": latitude, "longitude": longitude})
        return None

def get_spot_info(logger):
    """Fetch spot info from the database.

    Returns:
        list: A list of tuples representing spot information (id, latitude, longitude).
    """
    with PostgresConnection.from_env(logger=logger, analytics=True) as db_connection:
        spots = db_connection.select("reference.spot_info", "id, latitude, longitude")
    
    if not spots:
        logger.log_json("WARNING", "No spots found in the database")
        return []

    return spots

def insert_wind_data(spot_id, wind_data, logger):
    """Insert wind data into the database.

    Args:
        spot_id (int): The spot's unique identifier.
        wind_data (dict): A dictionary containing wind data to be inserted into the database.
        logger (Logger): The logger instance to log messages.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = {
        "spot_id": spot_id,
        "timestamp": timestamp,
        "wind_speed": wind_data['wind_speed'],
        "wind_direction": wind_data['wind_direction'],
        "wind_gust": wind_data['wind_gust']
    }

    with PostgresConnection.from_env(logger=logger, analytics=True) as db_connection:
        if db_connection.insert("ingested.wind_data", data):
            logger.log_json("INFO", "Wind data inserted successfully", {"spot_id": spot_id})
        else:
            logger.log_json("ERROR", "Failed to insert wind data", {"spot_id": spot_id, "data": data})

if __name__ == "__main__":
    with Logger(job_name="wind-scraper-hourly") as logger:
        spots = get_spot_info(logger)

        if not spots:
            logger.log_json("WARNING", "No spot information to process wind data for")

        for spot in spots:
            spot_id = spot[0]
            latitude, longitude = spot[1], spot[2]
            wind_data = fetch_wind_data(latitude, longitude, logger)

            if wind_data:
                insert_wind_data(spot_id, wind_data, logger)
            else:
                logger.log_json("WARNING", "Failed to retrieve or insert wind data", {"spot_id": spot_id})
