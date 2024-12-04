import json
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
from io import BytesIO
import requests
import matplotlib.font_manager as fm
from dotenv import load_dotenv

# from moesifasgi import MoesifMiddleware # DISABLED FOR NOW
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
ws_events_db = ws_client["events"]
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
    asyncio.create_task(monitor_table_changes())
    asyncio.create_task(monitor_event_changes())


async def shutdown_tasks():
    for connection in manager.active_connections:
        await connection.disconnect()
    await ws_client.close()
    await client.close()


app = FastAPI(lifespan=lifespan)

# Websocket helper functions


async def monitor_table_changes():
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


async def monitor_event_changes():
    """Monitor changes in the events collection and broadcast them to all connected clients."""
    try:
        change_stream = ws_events_db.events.watch()
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
# app.add_middleware(MoesifMiddleware, settings=moesif_settings) # DISABLED FOR NOW

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


from PIL import Image, ImageDraw, ImageFont
import textwrap
from pathlib import Path


def create_event_announcement(event_slug: str) -> BytesIO:
    """Create a medieval-themed announcement image with enhanced graphics."""
    event = events_db.events.find_one({"slug": event_slug})
    if not event:
        raise ValueError("Event not found")

    if isinstance(event["tables"], list) and all(
        isinstance(x, str) for x in event["tables"]
    ):
        tables = list(tables_db.tables.find({"event_slug": event_slug}))
    else:
        tables = event["tables"]

    # Image dimensions and colors
    WIDTH = 1920
    HEIGHT = max(1080, 600 + (len(tables) * 200))  # Base height plus 200px per table
    BACKGROUND = (44, 24, 16)  # Deep brown
    BORDER_COLOR = (139, 69, 19)  # Saddle brown
    TEXT_COLOR = (255, 215, 0)  # Gold
    HEADER_COLOR = (255, 223, 0)  # Bright gold
    TABLE_BG = (59, 36, 23)  # Darker brown

    def calculate_table_height(table):
        num_players = len(table.get("joined_players", []))
        return max(300, 160 + (num_players * 65))

    # Create base image
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(img)

    # Load fonts
    font_path = "resources/fonts/Cinzel-Regular.ttf"
    bold_font_path = "resources/fonts/Cinzel-Bold.ttf"
    header_font = ImageFont.truetype(bold_font_path, 120)
    date_font = ImageFont.truetype(font_path, 60)
    table_header_font = ImageFont.truetype(bold_font_path, 70)
    gm_font = ImageFont.truetype(font_path, 65)
    player_font = ImageFont.truetype(font_path, 40)
    footer_font = ImageFont.truetype(font_path, 50)

    # Draw main border
    border_width = 8
    draw.rectangle(
        [(border_width, border_width), (WIDTH - border_width, HEIGHT - border_width)],
        outline=BORDER_COLOR,
        width=border_width,
    )

    # Draw event header
    header_text = event["name"].upper()
    header_bbox = draw.textbbox((0, 0), header_text, font=header_font)
    header_width = header_bbox[2] - header_bbox[0]
    draw.text(
        ((WIDTH - header_width) // 2, 50), header_text, HEADER_COLOR, font=header_font
    )

    # Draw date
    start_date = event["start_date"]
    end_date = event["end_date"]
    date_text = start_date if start_date == end_date else f"{start_date} - {end_date}"
    date_bbox = draw.textbbox((0, 0), date_text, font=date_font)
    date_width = date_bbox[2] - date_bbox[0]
    draw.text(((WIDTH - date_width) // 2, 180), date_text, TEXT_COLOR, font=date_font)

    # Table layout calculations
    table_margin = 40
    table_padding = 30
    cols = min(3, len(tables))
    rows = (len(tables) + cols - 1) // cols
    table_width = (WIDTH - (table_margin * (cols + 1))) // cols
    start_y = 300

    # Calculate row heights
    max_height_per_row = []
    for row in range(rows):
        row_heights = []
        for col in range(cols):
            idx = row * cols + col
            if idx < len(tables):
                height = calculate_table_height(tables[idx])
                row_heights.append(height)
        max_height_per_row.append(max(row_heights) if row_heights else 0)

    # Draw tables
    current_y = start_y
    for row in range(rows):
        for col in range(cols):
            idx = row * cols + col
            if idx >= len(tables):
                continue

            table = tables[idx]
            x = table_margin + (col * (table_width + table_margin))
            y = current_y
            table_height = max_height_per_row[row]

            # Table background
            draw.rounded_rectangle(
                [(x, y), (x + table_width, y + table_height)],
                radius=20,
                fill=TABLE_BG,
                outline=BORDER_COLOR,
                width=3,
            )

            # Game name
            game_text = table["game_name"].upper()
            game_bbox = draw.textbbox((0, 0), game_text, font=table_header_font)
            game_width = game_bbox[2] - game_bbox[0]
            draw.text(
                (x + (table_width - game_width) // 2, y + 20),
                game_text,
                TEXT_COLOR,
                font=table_header_font,
            )

            # Game Master
            gm_text = f"{table['game_master']}"
            gm_bbox = draw.textbbox((0, 0), gm_text, font=gm_font)
            gm_width = gm_bbox[2] - gm_bbox[0]
            draw.text(
                (x + (table_width - gm_width) // 2, y + 100),
                gm_text,
                TEXT_COLOR,
                font=gm_font,
            )

            # Players
            players = [p["name"].upper() for p in table.get("joined_players", [])]
            player_y = y + 160
            player_y = y + 200  # Increased from 160
            for player in players:
                player_bbox = draw.textbbox((0, 0), player, font=player_font)
                player_width = player_bbox[2] - player_bbox[0]
                draw.text(
                    (x + (table_width - player_width) // 2, player_y),
                    player,
                    TEXT_COLOR,
                    font=player_font,
                )
                player_y += 50

        current_y += max_height_per_row[row] + table_margin

    # Footer with dice
    footer_text = "EMU RPG CLUB"
    footer_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
    footer_width = footer_bbox[2] - footer_bbox[0]
    footer_x = (WIDTH - footer_width) // 2
    footer_y = HEIGHT - 80

    # Draw footer text
    draw.text((footer_x, footer_y), footer_text, TEXT_COLOR, font=footer_font)

    # Save image
    img_buffer = BytesIO()
    img.save(img_buffer, format="PNG", quality=95)
    img_buffer.seek(0)

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
        "available_tables": 0,
        "tables": [],
        "slug": generate_slug(),
        "created_at": await fetch_current_datetime(),
        "available_seats": 0,
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
    await check_request(request, checkApiKey=True, checkOrigin=True)

    table = tables_db.tables.find_one({"slug": slug})
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    data = await request.json()
    old_quota = int(table["player_quota"])
    old_joined = int(table["total_joined_players"])
    new_quota = int(data.get("player_quota", old_quota))
    new_joined = int(data.get("total_joined_players", old_joined))

    update_data = {
        "game_name": data.get("game_name", table["game_name"]),
        "game_master": data.get("game_master", table["game_master"]),
        "player_quota": new_quota,
        "total_joined_players": new_joined,
        "joined_players": data.get("joined_players", table["joined_players"]),
        "slug": table["slug"],
        "created_at": data.get("created_at", table["created_at"]),
    }

    # Calculate seat changes
    old_available = old_quota - old_joined
    new_available = new_quota - new_joined
    seat_difference = new_quota - old_quota

    # Update tables collection
    tables_db.tables.update_one({"slug": slug}, {"$set": update_data})

    update_fields = {"available_seats": new_quota - old_quota}
    if old_available > 0 and new_available <= 0:
        update_fields["available_tables"] = -1
    elif old_available <= 0 and new_available > 0:
        update_fields["available_tables"] = 1

    events_db.events.update_one({"slug": table["event_slug"]}, {"$inc": update_fields})

    return JSONResponse(content={"message": "Table updated successfully"})


@app.delete("/api/admin/table/{slug}")
async def delete_table(slug: str, request: Request):
    await check_request(request, checkApiKey=True, checkOrigin=True)

    table = tables_db.tables.find_one({"slug": slug})
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    remaining_seats = int(table["player_quota"]) - int(table["total_joined_players"])

    events_db.events.update_one(
        {"slug": table["event_slug"]},
        {
            "$inc": {
                "total_tables": -1,
                "available_tables": -1 if remaining_seats > 0 else 0,
                "available_seats": -remaining_seats,
            },
            "$pull": {"tables": slug},
        },
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
    player_quota = int(table_data.get("player_quota", 0))

    new_table = {
        "game_name": table_data.get("game_name"),
        "game_master": table_data.get("game_master"),
        "player_quota": player_quota,
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
        {
            "$inc": {
                "total_tables": 1,
                "available_tables": 1,
                "available_seats": player_quota,
            },
            "$push": {"tables": new_table["slug"]},
        },
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
    event = events_db.events.find_one({"slug": table["event_slug"]})
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    if table["total_joined_players"] >= table["player_quota"]:
        raise HTTPException(status_code=400, detail="table is full")

    new_player = player.dict()
    new_player["registration_timestamp"] = await fetch_current_datetime()

    remaining_seats = int(table["player_quota"]) - (
        int(table["total_joined_players"]) + 1
    )
    tables_db.tables.update_one(
        {"slug": slug},
        {
            "$push": {"joined_players": new_player},
            "$inc": {"total_joined_players": 1},
        },
    )
    update_fields = {"available_seats": -1}
    if remaining_seats == 0:
        update_fields["available_tables"] = -1

    events_db.events.update_one({"slug": table["event_slug"]}, {"$inc": update_fields})

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
    """Delete the player from the table using the provided table slug and student_id."""
    await check_request(request, checkApiKey=True, checkOrigin=True)
    table = tables_db.tables.find_one({"slug": slug})

    result = tables_db.tables.update_one(
        {"slug": slug},
        {
            "$pull": {"joined_players": {"student_id": student_id}},
            "$inc": {"total_joined_players": -1},
        },
    )
    remaining_seats = int(table["player_quota"]) - (
        int(table["total_joined_players"]) - 1
    )
    update_fields = {"available_seats": 1}
    if remaining_seats == 1:  # Table becomes available
        update_fields["available_tables"] = 1

    events_db.events.update_one({"slug": table["event_slug"]}, {"$inc": update_fields})

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
                "available_seats": 1,
                "available_tables": 1,
            },
        )
    )

    return JSONResponse(content=events)


@app.get("/api/events/{slug}/tables")
async def get_event_tables(slug: str, request: Request):
    """Get all tables for the event using the provided slug."""
    await check_request(request, checkApiKey=False, checkOrigin=True)

    event = events_db.events.find_one({"slug": slug})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    tables = list(tables_db.tables.find({"event_slug": slug}, {"_id": 0}))
    return JSONResponse(content=tables)


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
    event = events_db.events.find_one({"slug": table["event_slug"]})
    if not table or not event:
        raise HTTPException(status_code=404, detail="table or event not found")

    for existing_player in table.get("joined_players", []):
        if existing_player["student_id"] == player.student_id:
            raise HTTPException(status_code=400, detail="Student is already registered")

    if len(player.student_id) != 8 or not player.student_id.isdigit():
        raise HTTPException(
            status_code=400, detail="Invalid student ID. Must be 8 digits."
        )

    if table["total_joined_players"] >= int(table["player_quota"]):
        raise HTTPException(status_code=400, detail="table is full, no available seats")

    # Convert to dictionary and add registration timestamp
    new_player = player.model_dump()
    new_player["registration_timestamp"] = (
        datetime.now().isoformat()
    )  # Store as ISO string

    tables_db.tables.update_one(
        {"slug": slug},
        {"$push": {"joined_players": new_player}, "$inc": {"total_joined_players": 1}},
    )
    remaining_seats = int(table["player_quota"]) - (
        int(table["total_joined_players"]) + 1
    )
    update_fields = {"available_seats": -1}
    if remaining_seats == 0:
        update_fields["available_tables"] = -1

    events_db.events.update_one({"slug": table["event_slug"]}, {"$inc": update_fields})

    return JSONResponse(content={"message": "Registration successful"})


@app.put("/api/admin/events/{slug}")
async def update_event(slug: str, request: Request):
    await check_request(request, checkApiKey=True, checkOrigin=True)

    event = events_db.events.find_one({"slug": slug})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    data = await request.json()
    update_data = {
        "name": data.get("name", event["name"]),
        "description": data.get("description", event["description"]),
        "start_date": data.get("start_date", event["start_date"]),
        "end_date": data.get("end_date", event["end_date"]),
    }

    events_db.events.update_one({"slug": slug}, {"$set": update_data})
    return JSONResponse(content={"message": "Event updated successfully"})


@app.post("/api/admin/generate-report")
async def generate_report(request: Request):
    await check_request(request, checkApiKey=True, checkOrigin=True)

    data = await request.json()
    report_type = data.get("type")
    language = data.get("language", "en")  # Default to English
    print(f"Generating report in {language} for type: {report_type}")

    # Language mappings
    translations = {
        "en": {
            "headers": "Event Name,Event Status,Start Date,End Date,Total Tables,Total Players,Total Player Quota,Fill Rate",
            "ongoing": "Ongoing",
            "finished": "Finished",
        },
        "tr": {
            "headers": "Etkinlik Adı,Etkinlik Durumu,Başlangıç Tarihi,Bitiş Tarihi,Toplam Masa,Toplam Oyuncu,Toplam Kontenjan,Doluluk Oranı",
            "ongoing": "Devam Ediyor",
            "finished": "Tamamlandı",
        },
    }

    headers = translations[language]["headers"]

    if report_type == "current":
        events_list = list(events_db.events.find({}, {"_id": 0}))
    elif report_type == "previous":
        events_list = list(previous_events_db.events.find({}, {"_id": 0}))
    elif report_type == "all":
        current = list(events_db.events.find({}, {"_id": 0}))
        previous = list(previous_events_db.events.find({}, {"_id": 0}))
        events_list = current + previous
    else:
        raise HTTPException(status_code=400, detail="Invalid report type")

    csv_rows = [headers]

    for event in events_list:
        total_players = 0
        total_quota = 0

        if isinstance(event["tables"], list) and all(
            isinstance(x, str) for x in event["tables"]
        ):
            tables = list(tables_db.tables.find({"event_slug": event["slug"]}))
        else:
            tables = event["tables"]

        for table in tables:
            total_players += int(table["total_joined_players"])
            total_quota += int(table["player_quota"])

        fill_rate = (total_players / total_quota * 100) if total_quota > 0 else 0
        status = (
            translations[language]["ongoing"]
            if event["is_ongoing"]
            else translations[language]["finished"]
        )

        csv_rows.append(
            f"{event['name']},"
            f"{status},"
            f"{event['start_date']},"
            f"{event['end_date']},"
            f"{event['total_tables']},"
            f"{total_players},"
            f"{total_quota},"
            f"{fill_rate:.2f}%"
        )

    csv_content = "\n".join(csv_rows)
    return JSONResponse(content={"csv": csv_content})


@app.get("/api/admin/events/{slug}/announcement")
async def generate_event_announcement(slug: str, request: Request):
    """Generate an announcement image for an event."""
    await check_request(request, checkApiKey=True, checkOrigin=True)

    try:
        img_buffer = create_event_announcement(slug)
        return StreamingResponse(img_buffer, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    if DEV:
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")

        print(f"Processing file: {file.filename}")

        try:
            contents = await file.read()
            pdf_file = BytesIO(contents)

            if not file.filename.endswith(".pdf"):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid file type. Please upload a PDF file.",
                )

            pdf_reader = PdfReader(pdf_file)
            text_content = " ".join(
                page.extract_text().replace("\n", " ") for page in pdf_reader.pages
            )
            print(f"Extracted text length: {len(text_content)}")

            # Get the prompt from environment variable
            prompt = os.environ.get("CHARROLLER_PROMPT") + text_content

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
            raise HTTPException(
                status_code=500, detail=f"Error handling file: {str(e)}"
            )
        finally:
            await file.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
