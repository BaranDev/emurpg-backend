import json
from bson import ObjectId, Timestamp
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    File,
    UploadFile,
    Depends,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pymongo import MongoClient
from pymongo.errors import PyMongoError
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
import asyncio
from contextlib import asynccontextmanager
from bson.json_util import default

# Development mode flag to disable api key and origin checks
DEV = False

load_dotenv()


from motor.motor_asyncio import AsyncIOMotorClient

# MongoDB connection
ws_client = AsyncIOMotorClient(os.environ.get("MONGO_URI"))
client = MongoClient(os.environ.get("MONGO_URI"))
events_db = client["events"]
previous_events_db = client["previous_events"]
tables_db = client["tables"]
ws_tables_db = ws_client["tables"]
api_db = client["api_keys"]
admin_db = client["admin_accounts"]

# Lifespan context manager for MongoDB connection and WebSocket monitoring


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)


manager = ConnectionManager()  # Connection manager instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await startup_tasks()
        yield
    finally:
        await shutdown_tasks()


async def startup_tasks():
    asyncio.create_task(monitor_changes())


async def shutdown_tasks():
    for connection in manager.active_connections:
        await connection.disconnect()
    await ws_client.close()
    await client.close()


app = FastAPI(lifespan=lifespan)

# Websocket helper functions


async def monitor_changes():
    """Monitor changes in the tables collection and broadcast them to all connected clients."""
    try:
        change_stream = ws_tables_db.tables.watch()
        async for change in change_stream:
            # Clean the change document before broadcasting
            cleaned_change = json.loads(json.dumps(change, default=default))
            await manager.broadcast({"message": "Records updated"})
            print(f"Change broadcasted: {cleaned_change}")
    except PyMongoError as e:
        print(f"MongoDB change stream error: {e}")
    finally:
        await change_stream.close()


# WebSocket Endpoints #


@app.websocket("/ws/updates")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep the connection alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)


origins = ["*"] if DEV else ["https://events.emurpg.com"]

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Moesif middleware

Moesif_enpoints_to_skip = ["/api/charroller/process", "/api/admin/generate-tables"]
Moesif_content_types_to_skip = ["multipart/form-data"]


# Custom skip function for file uploads
async def custom_should_skip(request):
    """Checks if request should skip processing. Returns True for file uploads and specific endpoints."""
    if hasattr(request, "scope") and request.scope.get("_is_file_upload"):
        return True

    content_type = request.headers.get("content-type", "")
    path = request.url.path
    will_skip = any(ep in path for ep in Moesif_enpoints_to_skip) or any(
        ct in content_type for ct in Moesif_content_types_to_skip
    )
    print(f"Will skip: {will_skip}")
    return will_skip


## Should skip check using async mode
async def should_skip(request, response):
    """Custom middleware function to determine if a request should skip certain processing."""
    result = await custom_should_skip(request)
    return result


## Custom identify user function (if you want to track users)
async def identify_user(request, response):
    """Custom middleware function to identify the user from the request."""
    return request.client.host if request else None


## Moesif API settings
moesif_settings = {
    "APPLICATION_ID": os.environ.get("MOESIF_APPLICATION_ID"),
    "LOG_BODY": False,
    "DEBUG": False,
    "IDENTIFY_USER": identify_user,
    "SKIP": should_skip,
    "CAPTURE_OUTGOING_REQUESTS": True,
}

## Add Moesif middleware to the app
app.add_middleware(MoesifMiddleware, settings=moesif_settings)

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


class Table(BaseModel):
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
    player_quota: Optional[int] = Field(
        default=0
    )  # Added player_quota for compatibility


# Add new Pydantic models
class Event(BaseModel):
    name: str
    description: Optional[str]
    start_date: str
    end_date: str
    is_ongoing: bool = True
    total_tables: int = 0
    tables: List[str] = []  # List of table slugs
    slug: str
    created_at: str


class EventCreate(BaseModel):
    name: str
    description: Optional[str]
    start_date: str
    end_date: str


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
    if DEV:
        return True
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


async def check_origin(request: Request):
    """Check if the request origin is allowed (https://events.emurpg.com)."""
    if DEV:
        return True
    # Get the "Origin" header from the request
    origin_header = request.headers.get("origin")
    print(f"Got a {request.method} request from origin: {origin_header}")

    allowed_origin = "https://events.emurpg.com"

    # Check if the origin is missing or does not match the allowed origin
    if origin_header != allowed_origin:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid origin.")

    return True  # Origin is valid, proceed with the request


async def fetch_current_datetime():
    """Fetch the current datetime from Time API in Cyprus timezone."""
    return requests.get(
        "https://timeapi.io/api/time/current/zone?timeZone=Europe%2FAthens"
    ).json()["dateTime"]


async def check_request(
    request: Request, checkApiKey: bool = True, checkOrigin: bool = True
):
    if checkApiKey:
        await check_api_key(request)
    if checkOrigin:
        await check_origin(request)


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
            player_quota=int(row.get("player_quota", 0)),
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

    # First pass: Create manager entries and gather team information
    for emp in employees:
        if emp.is_manager:
            managers[emp.name] = {
                "game": emp.game_played or "Unknown",
                "team": [],
                "quota": emp.player_quota,
                "joined": 0,
            }

    # Second pass: Add team members and count joined players
    for emp in employees:
        if not emp.is_manager and emp.manager_name:
            if emp.manager_name in managers:
                managers[emp.manager_name]["team"].append(emp.name)
                managers[emp.manager_name]["joined"] += 1

    table_count = len(managers)
    if table_count == 0:
        raise ValueError("No tables found in the provided data")

    # Calculate layout dimensions
    cols = int(math.ceil(math.sqrt(table_count)))
    rows = int(math.ceil(table_count / cols))
    fig_width = cols * 5
    fig_height = rows * 4

    # Create figure with medieval theme
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), facecolor="#F2D2A9")
    ax.set_xlim(0, fig_width)
    ax.set_ylim(0, fig_height)
    ax.axis("off")

    # Set up table dimensions and spacing
    table_width = 4.5
    table_height = 3.5
    gapsize = 0.15
    margin_x = 0.5
    margin_y = fig_height - 0.5
    x = margin_x
    y = margin_y

    # Draw tables
    for manager, data in managers.items():
        # Create fancy box for table
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

        # Add manager name
        ax.text(
            x + table_width / 2,
            y - 0.4,
            manager,
            ha="center",
            va="center",
            fontweight="bold",
            fontsize=16,
            color="#8B4513",
            fontname="Cinzel",
        )

        # Add game name and player count
        ax.text(
            x + table_width / 2,
            y - 0.8,
            f"{data['game']}",
            ha="center",
            va="center",
            fontweight="bold",
            fontsize=14,
            color="#A0522D",
            fontname="Cinzel",
        )

        # Add player count
        ax.text(
            x + table_width / 2,
            y - 1.1,
            f"Players: {data['joined']}/{data['quota'] if data['quota'] > 0 else '∞'}",
            ha="center",
            va="center",
            fontsize=12,
            color="#654321",
            fontname="Cinzel",
        )

        # Add team members
        for i, member in enumerate(data["team"]):
            if i < 8:  # Limit to prevent overflow
                ax.text(
                    x + table_width / 2,
                    y - 1.5 - i * 0.25,
                    member,
                    ha="center",
                    va="center",
                    fontsize=12,
                    color="#654321",
                    fontname="Cinzel",
                )
            elif i == 8:
                ax.text(
                    x + table_width / 2,
                    y - 1.5 - i * 0.25,
                    f"+ {len(data['team']) - 8} more",
                    ha="center",
                    va="center",
                    fontsize=12,
                    color="#654321",
                    fontname="Cinzel",
                )

        # Move to next position
        x += table_width + gapsize
        if x + table_width > fig_width:
            y -= table_height + gapsize
            x = margin_x

    plt.tight_layout()
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format="png", dpi=300, bbox_inches="tight", pad_inches=0.2)
    img_buffer.seek(0)
    plt.close(fig)
    return img_buffer


# Admin Endpoints #
####################
# These endpoints are for the admins to interact with the event system, they return sensitive information.


# New Admin Endpoints for Events
@app.post("/api/admin/events")
async def create_event(event: EventCreate, request: Request):
    await check_request(request, checkApiKey=True, checkOrigin=True)

    new_event = {
        "name": event.name,
        "description": event.description,
        "start_date": event.start_date,
        "end_date": event.end_date,
        "is_ongoing": True,
        "total_tables": 0,
        "tables": [],
        "slug": generate_slug(),
        "created_at": await fetch_current_datetime(),
    }

    events_db.events.insert_one(new_event)
    return JSONResponse(
        content={"message": "Event created successfully", "slug": new_event["slug"]},
        status_code=201,
    )


@app.get("/api/admin/events")
async def get_admin_events(request: Request):
    await check_request(request, checkApiKey=True, checkOrigin=True)

    events = list(events_db.events.find({}, {"_id": 0}))
    return JSONResponse(content=events)


@app.put("/api/admin/events/{slug}/finish")
async def finish_event(slug: str, request: Request):
    await check_request(request, checkApiKey=True, checkOrigin=True)

    event = events_db.events.find_one({"slug": slug})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Get all tables for this event
    tables = list(tables_db.tables.find({"event_slug": slug}))
    for table in tables:
        table.pop("_id", None)  # Remove MongoDB _id

    # Update event with full table data and mark as finished
    event["tables"] = tables
    event["is_ongoing"] = False
    event.pop("_id", None)

    # Move to previous_events and cleanup
    previous_events_db.events.insert_one(event)
    events_db.events.delete_one({"slug": slug})
    tables_db.tables.delete_many({"event_slug": slug})

    return JSONResponse(content={"message": "Event finished and archived"})


@app.delete("/api/admin/events/{slug}")
async def delete_event(slug: str, request: Request):
    await check_request(request, checkApiKey=True, checkOrigin=True)

    event = events_db.events.find_one({"slug": slug})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Delete all tables associated with the event
    tables_db.tables.delete_many({"event_slug": slug})

    # Delete the event
    events_db.events.delete_one({"slug": slug})
    return JSONResponse(
        content={"message": "Event and associated tables deleted successfully"}
    )


@app.post("/api/admin/generate-tables")
async def generate_tables(request: Request, file: UploadFile = File(...)):
    """Generate medieval-themed tables from the uploaded CSV file."""
    await check_request(request, checkApiKey=True, checkOrigin=True)
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
    await check_request(request, checkApiKey=True, checkOrigin=True)

    table = list(tables_db.tables.find({}, {"_id": 0}))
    json_table = jsonable_encoder(table)

    return JSONResponse(content=json_table)


@app.post("/api/admin/create_admin")
async def create_admin(credentials: AdminCredentials, request: Request):
    """Create a new admin account with the provided credentials."""
    await check_request(request, checkApiKey=True, checkOrigin=True)

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
    await check_request(request, checkApiKey=True, checkOrigin=True)

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
    await check_request(request, checkApiKey=True, checkOrigin=True)

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
    await check_request(request, checkApiKey=True, checkOrigin=True)

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
    await check_request(request, checkApiKey=True, checkOrigin=True)

    table = tables_db.tables.find_one({"slug": slug})
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    # Remove table reference from event
    events_db.events.update_one(
        {"slug": table["event_slug"]},
        {"$inc": {"total_tables": -1}, "$pull": {"tables": slug}},
    )

    tables_db.tables.delete_one({"slug": slug})
    return JSONResponse(content={"message": "Table deleted successfully"})


@app.post("/api/admin/create_table/{event_slug}")
async def create_table(event_slug: str, request: Request):
    await check_request(request, checkApiKey=True, checkOrigin=True)

    event = events_db.events.find_one({"slug": event_slug})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if not event["is_ongoing"]:
        raise HTTPException(
            status_code=400, detail="Cannot add tables to finished events"
        )

    table_data = await request.json()
    new_table = {
        "game_name": table_data.get("game_name"),
        "game_master": table_data.get("game_master"),
        "player_quota": table_data.get("player_quota"),
        "total_joined_players": 0,
        "joined_players": [],
        "slug": generate_slug(),
        "event_slug": event_slug,
        "event_name": event["name"],
        "created_at": await fetch_current_datetime(),
    }

    tables_db.tables.insert_one(new_table)
    events_db.events.update_one(
        {"slug": event_slug},
        {"$inc": {"total_tables": 1}, "$push": {"tables": new_table["slug"]}},
    )

    return JSONResponse(
        content={"message": "Table created successfully", "slug": new_table["slug"]},
        status_code=201,
    )


@app.get("/api/admin/get_players/{slug}")
async def get_players(slug: str, request: Request):
    """Get the list of players for the table using the provided slug, returns sensitive data."""
    await check_request(request, checkApiKey=True, checkOrigin=True)

    table = tables_db.tables.find_one({"slug": slug}, {"_id": 0})
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    return JSONResponse(content={"players": table.get("joined_players", [])})


@app.post("/api/admin/add_player/{slug}")
async def add_player(slug: str, player: Player, request: Request):
    """Add a new player to the table using the provided slug."""
    await check_request(request, checkApiKey=True, checkOrigin=True)

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
    await check_request(request, checkApiKey=True, checkOrigin=True)

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
    await check_request(request, checkApiKey=True, checkOrigin=True)

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


@app.get("/api/events")
async def get_events(request: Request):
    await check_request(request, checkApiKey=False, checkOrigin=True)

    # Only return ongoing events with non-sensitive data
    events = list(
        events_db.events.find(
            {"is_ongoing": True},
            {
                "_id": 0,
                "name": 1,
                "description": 1,
                "start_date": 1,
                "end_date": 1,
                "total_tables": 1,
                "slug": 1,
            },
        )
    )

    return JSONResponse(content=events)


@app.get("/api/tables")
async def get_tables(request: Request, dependencies=[Depends(check_origin)]):
    """Get all tables from the database without sensitive data."""
    await check_request(request, checkApiKey=False, checkOrigin=True)
    tables = list(
        tables_db.tables.find({}, {"_id": 0, "joined_players": 0, "created_at": 0})
    )

    # Convert the tables into JSON serializable format
    json_tables = jsonable_encoder(tables)

    return JSONResponse(content=json_tables)


@app.get("/api/table/{slug}")
async def get_table(slug: str, request: Request):
    """Get the table details from the database using the provided slug without sensitive data."""
    await check_request(request, checkApiKey=False, checkOrigin=True)
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
async def register_table(slug: str, player: Player, request: Request):
    """Register a player for the table using the provided slug."""
    await check_request(request, checkApiKey=False, checkOrigin=True)
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
from llm import LLMHandler

llm_handler = LLMHandler()

# Initialize OpenAI client
client = OpenAI(
    base_url="https://api-inference.huggingface.co/v1/",
    api_key=os.environ.get("HUGGINGFACE_API_KEY"),
)


def parse_llm_response(response_text: str) -> dict:
    """Parses and cleans LLM response into valid JSON format"""
    # Remove any markdown formatting or extra text
    clean_text = (
        re.sub(r"```json\s*|\s*```", "", response_text).replace("\\", "").strip()
    )

    try:
        # Try to parse the JSON directly
        return json.loads(clean_text)
    except json.JSONDecodeError:
        # If that fails, try to find JSON object in the text
        json_match = re.search(r"\{.*\}", clean_text, re.DOTALL)
        if not json_match:
            raise ValueError("Invalid JSON response")
        return json.loads(json_match.group())


def validate_roll_format(roll_list: list) -> list:
    """
    Validates roll format while preserving original values.
    Only fixes obviously incorrect formats.
    """
    validated_rolls = []
    dice_pattern = re.compile(r"^(\d+d\d+([+-]\d+)?|DC \d+)$")

    for roll in roll_list:
        roll_name = roll.get("roll_name", "").strip()
        dice = roll.get("dice", "").strip()

        # Skip empty or invalid rolls
        if not roll_name or not dice:
            continue

        # Only fix dice notation if it's clearly wrong
        if not dice_pattern.match(dice) and not dice.startswith("DC "):
            # Check if it's just missing the 'd'
            if re.match(r"^\d+\d+([+-]\d+)?$", dice):
                # Fix common format error (e.g., "120" -> "1d20")
                dice = f"{dice[0]}d{dice[1:]}"
            # If it has a bonus but no dice, assume 1d20
            elif re.match(r"^[+-]\d+$", dice):
                dice = f"1d20{dice}"

        validated_rolls.append({"roll_name": roll_name, "dice": dice})

    return validated_rolls


@app.post("/api/charroller/process")
async def process_character_sheet(
    file: UploadFile = File(...), request: Request = None
):
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")

    print(f"Processing file: {file.filename}")

    try:
        contents = await file.read()
        pdf_file = BytesIO(contents)

        if not file.filename.endswith(".pdf"):
            raise HTTPException(
                status_code=400, detail="Invalid file type. Please upload a PDF file."
            )

        pdf_reader = PdfReader(pdf_file)
        text_content = " ".join(
            page.extract_text().replace("\n", " ") for page in pdf_reader.pages
        )

        print(f"Extracted text length: {len(text_content)}")

        prompt = (
            "SYSTEM: You are a D&D 5E character sheet analyzer that extracts rolls and abilities. Your task is to:"
            "\n1. Extract character name"
            "\n2. Preserve all basic ability checks and skills"
            "\n3. Add character-specific rolls by analyzing:"
            "   - Weapon proficiencies and attack bonuses"
            "   - Spell attack bonus and save DCs"
            "   - Class features and special abilities"
            "   - Racial traits"
            "\n\nINPUT: D&D 5E character sheet text"
            "\nOUTPUT: JSON with character_name and comprehensive roll_list\n\n"
            "RULES FOR ROLL EXTRACTION:"
            "\n- Attack rolls: Add proficiency + ability modifier"
            "\n- Damage rolls: Include ability modifier and any bonuses"
            "\n- Spell attacks: Use spell attack bonus"
            "\n- Save DCs: Format as 'DC X [Type] Save'"
            "\n- Class abilities: Include action type and resource cost"
            "\n\nEXAMPLE OUTPUT:"
            """
            {
                "character_name": "Thorin Ironheart",
                "roll_list": [
                    {"roll_name": "Longsword Attack", "dice": "1d20+5"},
                    {"roll_name": "Longsword Damage", "dice": "1d8+3"},
                    {"roll_name": "Strength Check", "dice": "1d20+3"},
                    {"roll_name": "Athletics", "dice": "1d20+5"},
                    {"roll_name": "Fireball Damage", "dice": "8d6"},
                    {"roll_name": "Spell Save DC", "dice": "DC 15"},
                    {"roll_name": "Second Wind Healing", "dice": "1d10+3"},
                    {"roll_name": "Initiative", "dice": "1d20+2"}
                ]
            }
            """
            "\n\nBASE TEMPLATE TO MODIFY (PRESERVE AND EXTEND):"
            """{
                "character_name": "(Extract from sheet)",
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
                    {"roll_name": "Persuasion", "dice": "1d20+N"}
                ]
            }"""
            "\n\nKEY EXTRACTION PRIORITIES:"
            "\n1. Character Name (required)"
            "\n2. Basic Ability Checks (preserve existing)"
            "\n3. Skill Checks (preserve existing)"
            "\n4. Weapon Attacks:"
            "\n   - Format: '[Weapon] Attack' (1d20 + attack bonus)"
            "\n   - Format: '[Weapon] Damage' (weapon die + modifiers)"
            "\n5. Spellcasting:"
            "\n   - Format: '[Spell] Attack' (1d20 + spell attack)"
            "\n   - Format: '[Spell] Damage' (spell damage dice)"
            "\n   - Include save DCs"
            "\n6. Class Features:"
            "\n   - Format: '[Feature] Check' or '[Feature] Roll'"
            "\n   - Include healing, bonus actions, reactions"
            "\n7. Special Abilities:"
            "\n   - Racial traits"
            "\n   - Background features"
            "\n   - Magic item abilities"
            "\n\nFORMATTING RULES:"
            "\n- Use standard dice notation: 'NdM+X' or 'NdM-X'"
            "\n- Keep roll names clear and concise (1-4 words)"
            "\n- Include all modifiers and bonuses"
            "\n- No explanatory text or formatting"
            "\n- Raw JSON output only"
            "\n\nPROCESS THIS CHARACTER SHEET:"
            f"\n{text_content}"
        )

        # Process with LLM
        stream = client.chat.completions.create(
            model="meta-llama/Meta-Llama-3-8B-Instruct",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            stream=True,
            temperature=0.2,
        )

        response_text = "".join(
            chunk.choices[0].delta.content
            for chunk in stream
            if hasattr(chunk.choices[0].delta, "content")
        )

        # Parse and validate response
        response_json = parse_llm_response(response_text)
        validated_rolls = validate_roll_format(response_json.get("roll_list", []))

        response_data = {
            "character_name": response_json.get("character_name", "Unknown"),
            "roll_list": validated_rolls,
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        print(f"Error handling file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error handling file: {str(e)}")
    finally:
        await file.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
