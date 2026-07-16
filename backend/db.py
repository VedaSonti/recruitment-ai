"""
db.py
-----
Single place that connects to MongoDB Atlas and exposes the collections
your app needs. Every other file imports from here instead of
creating its own connection — one connection, reused everywhere.
"""

import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    raise RuntimeError(
        "MONGODB_URI not found in .env file. "
        "Add it as MONGODB_URI=mongodb+srv://... before running the app."
    )

mongo_client = AsyncIOMotorClient(MONGODB_URI)
db = mongo_client["recruitment_ai"]

# Collections
jobs_collection = db["jobs"]
candidates_collection = db["candidates"]
matches_collection = db["matches"]
recruiters_collection = db["recruiters"]
clients_collection = db["clients"]
generated_profiles_collection = db["generated_profiles"]
interviews_collection = db["interviews"]
