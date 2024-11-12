import json
from fastapi import FastAPI, HTTPException, Request, File, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pymongo import MongoClient
from datetime import datetime
import secrets
import os
from hashlib import sha256
from pydantic import BaseModel, Field
from typing import List, Optional
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import csv
from io import BytesIO
import requests
import math
import matplotlib.font_manager as fm
from dotenv import load_dotenv
from moesifasgi import MoesifMiddleware

load_dotenv()


# API monitoring middleware helper function for Moesif
async def custom_identify_user_id(request: Request, response: JSONResponse):
    return request.client.host


moesif_settings = {
    "APPLICATION_ID": os.environ.get("MOESIF_APPLICATION_ID"),
    "LOG_BODY": True,
    "CAPTURE_OUTGOING_REQUESTS": True,
    "IDENTIFY_USER": custom_identify_user_id,
}

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://events.emurpg.com"],  # PROD: https://events.emurpg.com
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Moesif middleware for API monitoring
app.add_middleware(MoesifMiddleware, settings=moesif_settings)

# MongoDB connection
client = MongoClient(os.environ.get("MONGO_URI"))
events_db = client["events"]
previous_events_db = client["previous_events"]
tables_db = client["tables"]
api_db = client["api_keys"]
admin_db = client["admin_accounts"]

# Add fonts
font_dir = "resources/fonts"
font_files = fm.findSystemFonts(fontpaths=[font_dir])
for font_file in font_files:
    fm.fontManager.addfont(font_file)


# Pydantic models


class Player(BaseModel):
    name: str
    student_id: str
    table_id: str
    seat_id: int
    contact: Optional[str] = None


class PlayerUpdate(BaseModel):
    name: str
    student_id: str
    table_id: str
    seat_id: int
    contact: Optional[str] = None


class Event(BaseModel):
    game_name: str
    game_master: str
    player_quota: int
    total_joined_players: int = 0
    joined_players: List[Player] = []
    slug: str
    created_at: str


class AdminCredentials(BaseModel):
    username: str
    hashedPassword: str


class Member(BaseModel):
    name: str
    is_manager: bool
    manager_name: Optional[str] = Field(default=None)
    game_played: Optional[str] = Field(default=None)


# Helper functions #


# Event registration helper functions
def generate_slug(length=8):
    """Generate a random slug for the table and event."""
    return secrets.token_urlsafe(length)


def generate_api_key(length=32, owner=""):
    """Generate a new API key for the given owner."""
    if owner == "":
        return "Owner name is required to generate an API key"
    new_api_key = secrets.token_urlsafe(length)
    api_db.api_keys.insert_one(
        {"api_key": new_api_key, "owner": owner, "used_times": []}
    )
    return new_api_key


async def check_api_key(request: Request):
    """Check if the API key is valid and exists in the database."""
    # Extract the "apiKey" header from the request
    api_key_header = request.headers.get("apiKey")

    if not api_key_header:
        # Raise error if the API key header is missing
        raise HTTPException(status_code=400, detail="Missing API Key.")

    try:
        # Attempt to parse the API key as JSON if it has { } format
        if api_key_header.startswith("{") and api_key_header.endswith("}"):
            api_key_data = json.loads(api_key_header)
            api_key = api_key_data.get("apiKey")
        else:
            # Otherwise, assume it's a plain string
            api_key = api_key_header
    except json.JSONDecodeError:
        # Fallback to treat as plain string if JSON parsing fails
        api_key = api_key_header

    # Check if the API key exists in the database
    status = api_db.api_keys.find_one({"api_key": api_key})
    if status:
        # Update the usage time in the database
        current_time = await fetch_current_datetime()
        api_db.api_keys.update_one(
            {"api_key": api_key}, {"$push": {"used_times": current_time}}
        )
        return True

    # Raise error if the API key is invalid
    raise HTTPException(status_code=401, detail="Unauthorized")


async def fetch_current_datetime():
    """Fetch the current datetime from Time API in Cyprus timezone."""
    return requests.get(
        "https://timeapi.io/api/time/current/zone?timeZone=Europe%2FAthens"
    ).json()["dateTime"]


# Table generator helper functions
def process_csv(file: UploadFile) -> List[Member]:
    """Process the uploaded CSV file and return a list of Member objects."""
    content = file.file.read().decode("utf-8").splitlines()
    reader = csv.DictReader(content)
    employees = []
    for row in reader:
        employee = Member(
            name=row["isim"],
            is_manager=bool(int(row["yonetici_mi"])),
            manager_name=row.get("birlikte_oynadigi_yonetici", ""),
            game_played=row.get("oynattigi_oyun", ""),
        )
        employees.append(employee)
    return employees


def fetch_image(url: str) -> BytesIO:
    """Fetch an image from the given URL and return it as a BytesIO object."""
    response = requests.get(url)
    return BytesIO(response.content)


def create_medieval_tables(employees: List[Member]) -> BytesIO:
    """Create a medieval-themed table layout from the given list of employees."""
    managers = {}
    for emp in employees:
        if emp.is_manager:
            managers[emp.name] = {"game": emp.game_played or "Unknown", "team": []}
        elif emp.manager_name:
            if emp.manager_name not in managers:
                managers[emp.manager_name] = {"game": "Unknown", "team": []}
            managers[emp.manager_name]["team"].append(emp.name)

    table_count = len(managers)
    cols = int(math.ceil(math.sqrt(table_count)))
    rows = int(math.ceil(table_count / cols))
    fig_width = cols * 5
    fig_height = rows * 4

    fig, ax = plt.subplots(figsize=(fig_width, fig_height), facecolor="#F2D2A9")
    ax.set_xlim(0, fig_width)
    ax.set_ylim(0, fig_height)
    ax.axis("off")

    bg_image = fetch_image(
        "https://raw.githubusercontent.com/BaranDev/BaranDev/refs/heads/main/hosted%20files/RECT_EMURPG%20DIGITAL%20BANNER.png"
    )
    ax.imshow(
        plt.imread(bg_image),
        extent=[0, fig_width, 0, fig_height],
        aspect="auto",
        alpha=0.7,
    )

    table_width = 4.5
    table_height = 3.5
    gapsize = 0.15
    table_groups_x_margin = 0.5
    table_groups_y_margin = fig_height - 0.5
    x = table_groups_x_margin
    y = table_groups_y_margin

    for manager, data in managers.items():
        fancy_box = FancyBboxPatch(
            (x, y - table_height),
            table_width,
            table_height,
            boxstyle="round,pad=0.02,rounding_size=0.02",
            ec=(0.4, 0.2, 0.0),
            fc=(0.9, 0.8, 0.7),
            alpha=0.8,
        )
        ax.add_patch(fancy_box)

        ax.text(
            x + table_width / 2,
            y - 0.4,
            manager,
            ha="center",
            va="center",
            fontweight="demibold",
            fontsize=16,
            color="#8B4513",
            fontname="Cinzel",
        )

        ax.text(
            x + table_width / 2,
            y - 0.8,
            f"{data['game']}",
            ha="center",
            va="center",
            fontweight="extra bold",
            fontsize=18,
            color="#A0522D",
            fontname="Cinzel",
        )

        for i, member in enumerate(data["team"]):
            ax.text(
                x + table_width / 2,
                y - 1.2 - i * 0.3,
                member,
                ha="center",
                va="center",
                fontweight="roman",
                fontsize=16,
                color="#654321",
                fontname="Cinzel",
            )

        x += table_width + gapsize
        if x + table_width > fig_width:
            y -= table_height + gapsize
            x = table_groups_x_margin

    plt.tight_layout()
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format="png", dpi=300, bbox_inches="tight", pad_inches=0)
    img_buffer.seek(0)
    plt.close(fig)
    return img_buffer


# Admin Endpoints #
####################
# These endpoints are for the admins to interact with the event system, they return sensitive information.


@app.post("/api/admin/generate-tables")
async def generate_tables(request: Request, file: UploadFile = File(...)):
    """Generate medieval-themed tables from the uploaded CSV file."""
    # Validate API key
    await check_api_key(request)

    # Validate file type
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400, detail="Invalid file type. Please upload a CSV file."
        )

    try:
        employees = process_csv(file)
        if not employees:
            raise ValueError("No valid data found in the CSV file.")
        img_buffer = create_medieval_tables(employees)
        return StreamingResponse(img_buffer, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@app.get("/api/admin/tables")
async def get_tables(request: Request):
    """Get all tables from the database with all the sensitive data."""
    await check_api_key(request)

    table = list(tables_db.tables.find({}, {"_id": 0}))
    json_table = jsonable_encoder(table)

    return JSONResponse(content=json_table)


@app.post("/api/admin/create_admin")
async def create_admin(credentials: AdminCredentials, request: Request):
    """Create a new admin account with the provided credentials."""
    await check_api_key(request)

    new_admin = {
        "username": credentials.username,
        "password": credentials.hashedPassword,
    }
    password = new_admin["password"].encode("utf-8")
    hashed_password = sha256(password).hexdigest()
    new_admin["password"] = hashed_password
    admin_db.admin_accounts.insert_one(new_admin)
    return JSONResponse(content={"username": new_admin["username"]}, status_code=201)


@app.post("/api/admin/checkcredentials")
async def check_admin_credentials(credentials: AdminCredentials, request: Request):
    """Check if the provided admin credentials are correct."""
    await check_api_key(request)

    admin_account = admin_db.admin_accounts.find_one({"username": credentials.username})
    if not admin_account:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if admin_account["password"] == credentials.hashedPassword:
        return JSONResponse(content={"message": "Credentials are correct"})
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/api/admin/table/{slug}")
async def get_table(slug: str, request: Request):
    """Get the table details from the database using the provided slug with sensitive data."""
    await check_api_key(request)

    # Fetch the table from the database using the provided slug
    table = tables_db.tables.find_one({"slug": slug}, {"_id": 0})

    if table:
        serialized_table = jsonable_encoder(
            table
        )  # Convert non-serializable fields (like datetime)
        return JSONResponse(content={"status": "success", "data": serialized_table})

    # If the table is not found, raise a 404 error
    raise HTTPException(status_code=404, detail="Table not found")


@app.post("/api/admin/table/{slug}")
async def update_table(slug: str, request: Request):
    """Update the table details using the provided slug."""
    await check_api_key(request)

    table = tables_db.tables.find_one({"slug": slug})
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    data = await request.json()
    update_data = {
        "game_name": data.get("game_name", table["game_name"]),
        "game_master": data.get("game_master", table["game_master"]),
        "player_quota": int(data.get("player_quota", table["player_quota"])),
        "total_joined_players": data.get(
            "total_joined_players", table["total_joined_players"]
        ),
        "joined_players": data.get("joined_players", table["joined_players"]),
        "slug": table["slug"],
        "created_at": data.get("created_at", table["created_at"]),
    }

    tables_db.tables.update_one({"slug": slug}, {"$set": update_data})
    return JSONResponse(content={"message": "Table updated successfully"})


@app.delete("/api/admin/table/{slug}")
async def delete_table(slug: str, request: Request):
    """Delete the table using the provided slug."""
    await check_api_key(request)

    # Find and delete the table by slug
    result = tables_db.tables.delete_one({"slug": slug})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Table not found")

    # Return a success response
    return JSONResponse(content={"message": "Table deleted successfully"})


@app.post("/api/admin/create_table")
async def create_table(request: Request):
    """Create a new table using the provided: game_name, game_master, player_quota."""
    await check_api_key(request)

    # Parse the request body to get the table data
    try:
        table_data = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid request body")

    # Create new table data
    new_table = {
        "game_name": table_data.get("game_name"),
        "game_master": table_data.get("game_master"),
        "player_quota": table_data.get("player_quota"),
        "total_joined_players": 0,
        "joined_players": [],
        "slug": generate_slug(),
        "created_at": await fetch_current_datetime(),
    }

    # Insert the new table into the database
    tables_db.tables.insert_one(new_table)

    # Return a success response with the table's slug
    return JSONResponse(
        content={"message": "Table created successfully", "slug": new_table["slug"]},
        status_code=201,
    )


@app.get("/api/admin/get_players/{slug}")
async def get_players(slug: str, request: Request):
    """Get the list of players for the table using the provided slug, returns sensitive data."""
    await check_api_key(request)

    table = tables_db.tables.find_one({"slug": slug}, {"_id": 0})
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    return JSONResponse(content={"players": table.get("joined_players", [])})


@app.post("/api/admin/add_player/{slug}")
async def add_player(slug: str, player: Player, request: Request):
    """Add a new player to the table using the provided slug."""
    await check_api_key(request)

    table = tables_db.tables.find_one({"slug": slug})
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    if table["total_joined_players"] >= table["player_quota"]:
        raise HTTPException(status_code=400, detail="table is full")

    new_player = player.dict()
    new_player["registration_timestamp"] = await fetch_current_datetime()

    tables_db.tables.update_one(
        {"slug": slug},
        {
            "$push": {"joined_players": new_player},
            "$inc": {"total_joined_players": 1},
        },
    )

    return JSONResponse(content={"message": "Player added successfully"})


@app.put("/api/admin/update_player/{slug}/{student_id}")
async def update_player(
    slug: str, student_id: str, player: PlayerUpdate, request: Request
):
    """Update the player details for the table using the provided slug and student_id."""
    await check_api_key(request)

    result = tables_db.tables.update_one(
        {"slug": slug, "joined_players.student_id": student_id},
        {"$set": {"joined_players.$": player.dict()}},
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Player not found")

    return JSONResponse(content={"message": "Player updated successfully"})


@app.delete("/api/admin/delete_player/{slug}/{student_id}")
async def delete_player(slug: str, student_id: str, request: Request):
    """Delete the player from the table using the provided slug and student_id."""
    await check_api_key(request)

    result = tables_db.tables.update_one(
        {"slug": slug},
        {
            "$pull": {"joined_players": {"student_id": student_id}},
            "$inc": {"total_joined_players": -1},
        },
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Player not found")

    return JSONResponse(content={"message": "Player deleted successfully"})


# User Endpoints #
####################
# These endpoints are for the users to interact with the event system, they don't return sensitive information.


@app.get("/api/tables")
async def get_tables(request: Request):
    """Get all tables from the database without sensitive data."""
    request_str = f"Method: {request.method}, URL: {request.url}, Headers: {dict(request.headers)}, Query Params: {dict(request.query_params)}"
    print(f"got the request {request_str}")
    tables = list(
        tables_db.tables.find({}, {"_id": 0, "joined_players": 0, "created_at": 0})
    )

    # Convert the tables into JSON serializable format
    json_tables = jsonable_encoder(tables)

    return JSONResponse(content=json_tables)


@app.get("/api/table/{slug}")
async def get_table(slug: str, request: Request):
    """Get the table details from the database using the provided slug without sensitive data."""
    # Fetch the table from the database using the provided slug
    table = tables_db.tables.find_one(
        {"slug": slug}, {"_id": 0, "joined_players": 0, "created_at": 0}
    )

    if table:
        serialized_table = jsonable_encoder(
            table
        )  # Convert non-serializable fields (like datetime)
        return JSONResponse(content={"status": "success", "data": serialized_table})

    # If the table is not found, raise a 404 error
    raise HTTPException(status_code=404, detail="Table not found")


@app.post("/api/register/{slug}")
async def register_table(slug: str, player: Player):
    """Register a player for the table using the provided slug."""
    table = tables_db.tables.find_one({"slug": slug})
    if not table:
        raise HTTPException(status_code=404, detail="table not found")

    for existing_player in table.get("joined_players", []):
        if existing_player["student_id"] == player.student_id:
            raise HTTPException(status_code=400, detail="Student is already registered")

    if len(player.student_id) != 8 or not player.student_id.isdigit():
        raise HTTPException(
            status_code=400, detail="Invalid student ID. Must be 8 digits."
        )

    if table["total_joined_players"] >= table["player_quota"]:
        raise HTTPException(status_code=400, detail="table is full, no available seats")

    # Convert to dictionary and add registration timestamp
    new_player = player.dict()
    new_player["registration_timestamp"] = (
        datetime.now().isoformat()
    )  # Store as ISO string

    tables_db.tables.update_one(
        {"slug": slug},
        {
            "$push": {"joined_players": new_player},
            "$inc": {"total_joined_players": 1},
        },
    )

    return JSONResponse(content={"message": "Registration successful"})


# CHARROLLER (WIP - 11.12.24)#
####################
# These endpoints are for the character sheet processing using an LLM model (still testing).
# Once done, these endpoints will give the following functionalities:
## User can upload a D&D character sheet PDF, then the API will process it and return a modified roll list to be displayed in the frontend.
## The roll list will include all basic D&D stats and skills, as well as any additional rolls based on the character sheet.

from PyPDF2 import PdfReader
from openai import OpenAI
import re
import json
import os

# Initialize OpenAI client
client = OpenAI(
    base_url="https://api-inference.huggingface.co/v1/",
    api_key=os.environ.get("HUGGINGFACE_API_KEY"),
)

# Initialize constants for D&D character sheet processing

DND_STATS = [
    "Strength",
    "Dexterity",
    "Constitution",
    "Intelligence",
    "Wisdom",
    "Charisma",
]

DND_SKILLS = {
    "Strength": ["Athletics"],
    "Dexterity": ["Acrobatics", "Sleight of Hand", "Stealth"],
    "Intelligence": ["Arcana", "History", "Investigation", "Nature", "Religion"],
    "Wisdom": ["Animal Handling", "Insight", "Medicine", "Perception", "Survival"],
    "Charisma": ["Deception", "Intimidation", "Performance", "Persuasion"],
}

# Helper functions for character sheet processing


def validate_and_format_dice(dice_str):
    """Validate and format dice notation."""
    print(f"Validating dice notation: {dice_str}")

    # Remove any escape characters and extra spaces
    dice_str = dice_str.strip().replace("\\", "")
    print(f"Cleaned dice string: {dice_str}")

    # Pattern for standard dice notation
    dice_pattern = re.compile(r"^(\d+d\d+)?([+-]\d+)?$")
    modifier_pattern = re.compile(r"^([A-Za-z]+\s+)?Modifier\s*([+-]\s*\d+)?$")

    if dice_pattern.match(dice_str):
        print(f"Standard dice notation found: {dice_str}")
        return dice_str
    elif modifier_pattern.match(dice_str):
        print(f"Modifier notation found: {dice_str}")
        mod_match = re.search(r"([+-]\s*\d+)", dice_str)
        modifier = mod_match.group(1).replace(" ", "") if mod_match else "+0"
        result = f"1d20{modifier}"
        print(f"Converted to: {result}")
        return result
    else:
        print(f"Non-standard notation, checking for compound dice: {dice_str}")
        compound_pattern = re.compile(r"(\d+d\d+([+-]\d+)?)")
        matches = compound_pattern.findall(dice_str)
        if matches:
            print(f"Found compound dice, using first match: {matches[0][0]}")
            return matches[0][0]
        print("No valid dice notation found, using default: 1d20+0")
        return "1d20+0"


def clean_json_response(response_text):
    """Clean and parse JSON response from LLM."""
    print("Starting JSON response cleaning")
    print(f"Original response text: {response_text[:200]}...")  # Log first 200 chars

    # Remove markdown code blocks
    response_text = re.sub(r"```json\s*|\s*```", "", response_text)
    print("Removed markdown code blocks")

    # Remove escaped characters and normalize whitespace
    response_text = response_text.replace("\\", "").strip()
    print(f"Cleaned response text: {response_text}")

    try:
        json_data = json.loads(response_text)
        print("Successfully parsed JSON directly")
        return json_data
    except json.JSONDecodeError as e:
        print(f"Initial JSON parsing failed: {str(e)}")
        print("Attempting to extract JSON using regex")

        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not json_match:
            print("Could not extract JSON with regex")
            raise ValueError("Could not extract valid JSON from model response")

        extracted_json = json_match.group()
        print(f"Extracted JSON: {extracted_json}...")
        return json.loads(extracted_json)


def ensure_basic_rolls(roll_list):
    """Ensure all basic D&D stats and skills are included in the roll list."""
    print("Checking for missing basic rolls")
    print(f"Initial roll list size: {len(roll_list)}")

    existing_rolls = {roll["roll_name"].lower(): roll for roll in roll_list}
    print(f"Existing roll names: {list(existing_rolls.keys())}")

    # Add missing ability checks
    for stat in DND_STATS:
        check_name = f"{stat} Check"
        if check_name.lower() not in existing_rolls:
            print(f"Adding missing ability check: {check_name}")
            roll_list.append({"roll_name": check_name, "dice": "1d20+0"})

    # Add missing skills
    for ability, skills in DND_SKILLS.items():
        for skill in skills:
            if skill.lower() not in existing_rolls:
                print(f"Adding missing skill: {skill}")
                roll_list.append({"roll_name": skill, "dice": "1d20+0"})

    print(f"Final roll list size: {len(roll_list)}")
    return roll_list


@app.post("/api/charroller/process")
async def process_character_sheet(file: UploadFile = File(...)):
    """Process the D&D character sheet PDF and generate a modified roll list."""
    print("Starting character sheet processing")
    print(f"Received file: {file.filename}")

    try:
        # Read PDF file content
        print("Reading PDF file")
        pdf_reader = PdfReader(file.file)
        text_content = " ".join(
            page.extract_text().replace("\n", " ") for page in pdf_reader.pages
        )
        print(f"Extracted text length: {len(text_content)} characters")

        # Construct prompt
        print("Constructing LLM prompt")
        prompt = (
            "You are an API endpoint that modifies and extends a base D&D character roll list. "
            "Start with this base JSON and modify it based on the character sheet:\n\n"
            """
            {
                "character_name": "(Extracted from the sheet)",
                "roll_list": [
                    {"roll_name": "Attack", "dice": "NdM+X"},
                    {"roll_name": "Strength Check", "dice": "1d20+N"},
                    {"roll_name": "Dexterity Check", "dice": "1d20+N"},
                    {"roll_name": "Constitution Check", "dice": "1d20+N"},
                    {"roll_name": "Intelligence Check", "dice": "1d20+N"},
                    {"roll_name": "Wisdom Check", "dice": "1d20+N"},
                    {"roll_name": "Charisma Check", "dice": "1d20+N"},
                    {"roll_name": "Athletics", "dice": "1d20+N"},
                    {"roll_name": "Acrobatics", "dice": "1d20+N"},
                    {"roll_name": "Sleight of Hand", "dice": "1d20+N"},
                    {"roll_name": "Stealth", "dice": "1d20+N"},
                    {"roll_name": "Arcana", "dice": "1d20+N"},
                    {"roll_name": "History", "dice": "1d20+N"},
                    {"roll_name": "Investigation", "dice": "1d20+N"},
                    {"roll_name": "Nature", "dice": "1d20+N"},
                    {"roll_name": "Religion", "dice": "1d20+N"},
                    {"roll_name": "Animal Handling", "dice": "1d20+N"},
                    {"roll_name": "Insight", "dice": "1d20+N"},
                    {"roll_name": "Medicine", "dice": "1d20+N"},
                    {"roll_name": "Perception", "dice": "1d20+N"},
                    {"roll_name": "Survival", "dice": "1d20+N"},
                    {"roll_name": "Deception", "dice": "1d20+N"},
                    {"roll_name": "Intimidation", "dice": "1d20+N"},
                    {"roll_name": "Performance", "dice": "1d20+N"},
                    {"roll_name": "Persuasion", "dice": "1d20+N"},
                    (CONTINUE WITH CHARACTER SPECIFIC ROLLS AFTER THIS!)
                ]
            }
            """
            "\n\nInstructions:"
            "\n1. Update the character_name from the sheet"
            "\n2. Update the modifiers for all existing rolls based on the character sheet"
            "\n3. Add all saving throws with proper modifiers"
            "\n4. Add all weapon attacks and damage rolls"
            "\n5. Add all spell attacks and damage rolls"
            "\n6. Add any special ability rolls"
            "\n\nRules:"
            "\n- Use only standard dice notation (e.g., '1d20+5', '2d6-1')"
            "\n- Keep roll names short (1-4 words maximum)"
            "\n- Do not add descriptions or extra text in roll names"
            "\n- RETURN ONLY THE MODIFIED JSON WITH NO ADDITIONAL TEXT, DON'T USE JSON BLOCK RESPOND WITH PLAIN TEXT WITH JSON FORMAT!!"
            f"\n\nAnalyze this character sheet and follow the instructions:\n{text_content}"
        )
        print(f"Prompt length: {len(prompt)} characters")

        # Get LLM response
        print("Sending request to LLM")
        stream = client.chat.completions.create(
            model="meta-llama/Meta-Llama-3-8B-Instruct",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            stream=True,
            temperature=0.2,
        )

        print("Processing LLM response stream")
        response_text = ""
        for chunk in stream:
            if hasattr(chunk.choices[0].delta, "content"):
                response_text += chunk.choices[0].delta.content
        print(f"Received response length: {len(response_text)} characters")
        print(f"Response preview: {response_text[:200]}...")

        # Clean and parse response
        print("Cleaning and parsing JSON response")
        response_json = clean_json_response(response_text)
        print(f"Parsed JSON structure: {list(response_json.keys())}")
        print(f"Roll list: \n{response_json}")

        response_data = {
            "character_name": response_json.get("character_name", "Unknown"),
            "roll_list": response_json.get("roll_list"),
        }
        print("Successfully processed character sheet")
        return JSONResponse(content=response_data)

    except Exception as e:
        print(f"Error processing character sheet: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error processing character sheet: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
