from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from pymongo.database import Database

# Image dimensions
IMAGE_WIDTH = 1920  # Width of the announcement image in pixels
BASE_HEIGHT = 1080  # Base height for each section (A size) in pixels

# Spacing constants
BORDER_WIDTH = 8  # Width of the main border in pixels
TABLE_MARGIN = 40  # Margin between tables in pixels
TABLE_PADDING = 30  # Internal padding inside tables in pixels
TABLE_RADIUS = 20  # Radius for rounded rectangle corners in pixels

# Section heights
BANNER_HEIGHT = 100  # Height of the club banner at top in pixels
TITLE_SECTION_HEIGHT = 300  # Height for event name and date section in pixels
SECTION_GAP = 40  # Gap between main players and backup players sections in pixels
BACKUP_HEADER_HEIGHT = 150  # Height for the backup section header in pixels

# Text positioning
EVENT_NAME_Y_OFFSET = 40  # Y offset for event name from banner bottom in pixels
DATE_Y_OFFSET = 130  # Y offset for date text from event name in pixels
TABLES_Y_OFFSET = 100  # Y offset for tables from date text in pixels
BACKUP_TITLE_Y_OFFSET = 50  # Y offset for backup title from main section end
BACKUP_TABLES_Y_OFFSET = 150  # Y offset for backup tables from backup title
GAME_NAME_Y_OFFSET = 20  # Y offset for game name from table top in pixels
GM_NAME_Y_OFFSET = 60  # Y offset for GM name from game name in pixels
PLAYER_START_Y_OFFSET = 160  # Y offset for first player from GM name in pixels
PLAYER_SPACING = 50  # Vertical spacing between players in pixels
TABLE_BOTTOM_PADDING = 40  # Padding from last player to bottom of table
TABLE_BOTTOM_PADDING = 40  # Padding from last player to bottom of table

# Text truncation
MAX_GAME_NAME_CHARS = 25  # Maximum characters for game name before truncation

# Fixed text strings
CLUB_NAME_TEXT = "EMU RPG CLUB"  # Text for club name banner
BACKUP_TITLE_TEXT = "BACKUP PLAYER LIST"  # Text for backup section header
DATE_SEPARATOR_TEXT = " - "  # Separator for date range

# Fixed text strings
CLUB_NAME_TEXT = "EMU RPG CLUB"  # Text for club name banner
BACKUP_TITLE_TEXT = "BACKUP PLAYER LIST"  # Text for backup section header
DATE_SEPARATOR_TEXT = " - "  # Separator for date range

# Colors
BACKGROUND_COLOR = (44, 24, 16)  # Deep brown background color
BORDER_COLOR = (139, 69, 19)  # Saddle brown border color
TEXT_COLOR = (255, 215, 0)  # Gold text color
HEADER_COLOR = (255, 223, 0)  # Bright gold header color
CLUB_HEADER_COLOR = (255, 223, 0)  # Bright gold for club name
TABLE_BG_COLOR = (59, 36, 23)  # Darker brown table background color

# Font sizes
CLUB_FONT_SIZE = 80  # Font size for club name
EVENT_NAME_FONT_SIZE = 120  # Font size for event name
DATE_FONT_SIZE = 60  # Font size for date text
BACKUP_HEADER_FONT_SIZE = 100  # Font size for backup section header
TABLE_HEADER_FONT_SIZE = 36  # Font size for game names
GM_FONT_SIZE = 30  # Font size for game master names
PLAYER_FONT_SIZE = 38  # Font size for player names


def create_event_announcement(
    event_slug: str, events_db: Database, tables_db: Database
) -> BytesIO:
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

    # Extract all backup players from tables
    backup_players = []
    for table in tables:
        if "backup_players" in table and table["backup_players"]:
            for player in table["backup_players"]:
                backup_players.append(
                    {
                        "name": player["name"],
                        "game_name": table["game_name"],
                        "game_master": table["game_master"],
                    }
                )

    # Calculate appropriate heights
    tables_height = calculate_tables_section_height(tables)
    backups_height = (
        calculate_backup_section_height(backup_players) if backup_players else 0
    )

    # Calculate total required height
    padding_bottom = 100  # Extra padding at bottom

    # Total height calculation to ensure everything is visible
    if backup_players:
        HEIGHT = (
            BANNER_HEIGHT
            + TITLE_SECTION_HEIGHT
            + tables_height
            + SECTION_GAP
            + BACKUP_TITLE_Y_OFFSET
            + BACKUP_HEADER_HEIGHT
            + backups_height
            + padding_bottom
        )
    else:
        HEIGHT = max(
            BASE_HEIGHT,
            BANNER_HEIGHT + TITLE_SECTION_HEIGHT + tables_height + padding_bottom,
        )

    # Create base image
    img = Image.new("RGB", (IMAGE_WIDTH, HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    # Load fonts
    font_path = "resources/fonts/Cinzel-Regular.ttf"
    bold_font_path = "resources/fonts/Cinzel-Bold.ttf"
    club_font = ImageFont.truetype(font_path, CLUB_FONT_SIZE)
    header_font = ImageFont.truetype(bold_font_path, EVENT_NAME_FONT_SIZE)
    date_font = ImageFont.truetype(font_path, DATE_FONT_SIZE)
    backup_header_font = ImageFont.truetype(bold_font_path, BACKUP_HEADER_FONT_SIZE)
    table_header_font = ImageFont.truetype(bold_font_path, TABLE_HEADER_FONT_SIZE)
    gm_font = ImageFont.truetype(font_path, GM_FONT_SIZE)
    player_font = ImageFont.truetype(font_path, PLAYER_FONT_SIZE)

    # Draw main border
    draw.rectangle(
        [
            (BORDER_WIDTH, BORDER_WIDTH),
            (IMAGE_WIDTH - BORDER_WIDTH, HEIGHT - BORDER_WIDTH),
        ],
        outline=BORDER_COLOR,
        width=BORDER_WIDTH,
    )

    # Draw club header banner
    draw.rectangle(
        [(0, 0), (IMAGE_WIDTH, BANNER_HEIGHT)],
        fill=BACKGROUND_COLOR,
        outline=BORDER_COLOR,
        width=2,
    )

    club_bbox = draw.textbbox((0, 0), CLUB_NAME_TEXT, font=club_font)
    club_width = club_bbox[2] - club_bbox[0]
    draw.text(
        ((IMAGE_WIDTH - club_width) // 2, 10),
        CLUB_NAME_TEXT,
        CLUB_HEADER_COLOR,
        font=club_font,
    )

    # Draw event header (title section)
    header_text = event["name"].upper()
    header_bbox = draw.textbbox((0, 0), header_text, font=header_font)
    header_width = header_bbox[2] - header_bbox[0]
    header_y = BANNER_HEIGHT + EVENT_NAME_Y_OFFSET
    draw.text(
        ((IMAGE_WIDTH - header_width) // 2, header_y),
        header_text,
        HEADER_COLOR,
        font=header_font,
    )

    # Draw date
    start_date = event["start_date"]
    end_date = event["end_date"]
    date_text = (
        start_date
        if start_date == end_date
        else f"{start_date}{DATE_SEPARATOR_TEXT}{end_date}"
    )
    date_bbox = draw.textbbox((0, 0), date_text, font=date_font)
    date_width = date_bbox[2] - date_bbox[0]
    date_y = header_y + DATE_Y_OFFSET
    draw.text(
        ((IMAGE_WIDTH - date_width) // 2, date_y), date_text, TEXT_COLOR, font=date_font
    )

    # Draw main player tables section
    tables_start_y = date_y + TABLES_Y_OFFSET
    main_section_end_y = draw_tables_section(
        draw,
        tables,
        IMAGE_WIDTH,
        tables_start_y,
        TABLE_BG_COLOR,
        BORDER_COLOR,
        TEXT_COLOR,
        table_header_font,
        gm_font,
        player_font,
    )

    # If we have backup players, add the backup section
    if backup_players:
        # Calculate position based on where the main section ends + spacing
        backup_section_start = main_section_end_y + SECTION_GAP

        # Draw backup player section header with specific offset from section start
        backup_header_bbox = draw.textbbox(
            (0, 0), BACKUP_TITLE_TEXT, font=backup_header_font
        )
        backup_header_width = backup_header_bbox[2] - backup_header_bbox[0]
        backup_header_y = backup_section_start + BACKUP_TITLE_Y_OFFSET
        draw.text(
            ((IMAGE_WIDTH - backup_header_width) // 2, backup_header_y),
            BACKUP_TITLE_TEXT,
            HEADER_COLOR,
            font=backup_header_font,
        )

        # Draw backup tables using same approach as main tables
        backup_tables = []
        for player in backup_players:
            # Convert backup player info to table-like structure
            backup_table = {
                "game_name": player["game_name"],
                "game_master": player["game_master"],
                "approved_players": [{"name": player["name"]}],
            }
            backup_tables.append(backup_table)

        # Draw backup tables below header with specific offset from header
        backup_tables_y = backup_header_y + BACKUP_TABLES_Y_OFFSET
        draw_tables_section(
            draw,
            backup_tables,
            IMAGE_WIDTH,
            backup_tables_y,
            TABLE_BG_COLOR,
            BORDER_COLOR,
            TEXT_COLOR,
            table_header_font,
            gm_font,
            player_font,
        )

    # Save image
    img_buffer = BytesIO()
    img.save(img_buffer, format="PNG", quality=95)
    img_buffer.seek(0)

    return img_buffer


def calculate_tables_section_height(tables):
    """Calculate the height needed for the tables section"""
    cols = min(3, len(tables))
    rows = (len(tables) + cols - 1) // cols

    # Calculate row heights
    total_height = 0
    for row in range(rows):
        row_heights = []
        for col in range(cols):
            idx = row * cols + col
            if idx < len(tables):
                table = tables[idx]
                num_players = len(table.get("approved_players", []))
                height = max(
                    300, 160 + (num_players * PLAYER_SPACING) + TABLE_BOTTOM_PADDING
                )
                row_heights.append(height)
        total_height += max(row_heights) if row_heights else 0
        total_height += TABLE_MARGIN

    return total_height


def calculate_backup_section_height(backup_players):
    """Calculate the height needed for the backup players section using same logic as main section"""
    if not backup_players:
        return 0

    # Convert backup players to table-like structure for consistent calculation
    backup_tables = []
    for player in backup_players:
        backup_tables.append(
            {
                "game_name": player["game_name"],
                "game_master": player["game_master"],
                "approved_players": [{"name": player["name"]}],
            }
        )

    # Use the same height calculation as for tables section
    return calculate_tables_section_height(backup_tables)


def draw_tables_section(
    draw,
    tables,
    width,
    start_y,
    table_bg,
    border_color,
    text_color,
    table_header_font,
    gm_font,
    player_font,
):
    """Draw the tables section with approved players"""
    # Table layout calculations
    cols = min(3, len(tables))
    rows = (len(tables) + cols - 1) // cols
    table_width = (width - (TABLE_MARGIN * (cols + 1))) // cols

    # Calculate row heights based on number of players
    max_height_per_row = []
    for row in range(rows):
        row_heights = []
        for col in range(cols):
            idx = row * cols + col
            if idx < len(tables):
                table = tables[idx]
                num_players = len(table.get("approved_players", []))
                height = max(
                    300, 160 + (num_players * PLAYER_SPACING) + TABLE_BOTTOM_PADDING
                )
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
            x = TABLE_MARGIN + (col * (table_width + TABLE_MARGIN))
            y = current_y
            table_height = max_height_per_row[row]

            # Table background
            draw.rounded_rectangle(
                [(x, y), (x + table_width, y + table_height)],
                radius=TABLE_RADIUS,
                fill=table_bg,
                outline=border_color,
                width=3,
            )

            # Game name - use consistent font size for all games
            game_text = table["game_name"].upper()

            # If game name is too long, truncate it with ellipsis
            if len(game_text) > MAX_GAME_NAME_CHARS:
                game_text = game_text[: MAX_GAME_NAME_CHARS - 3] + "..."

            game_bbox = draw.textbbox((0, 0), game_text, font=table_header_font)
            game_width = game_bbox[2] - game_bbox[0]
            draw.text(
                (x + (table_width - game_width) // 2, y + GAME_NAME_Y_OFFSET),
                game_text,
                text_color,
                font=table_header_font,
            )

            # Game Master - small gap between game name and GM name
            gm_text = f"{table['game_master']}"
            gm_bbox = draw.textbbox((0, 0), gm_text, font=gm_font)
            gm_width = gm_bbox[2] - gm_bbox[0]

            # If GM name is too long, truncate it with ellipsis
            if gm_width > table_width - 20:
                max_gm_chars = int(len(gm_text) * (table_width - 40) / gm_width)
                gm_text = gm_text[: max_gm_chars - 3] + "..."
                gm_bbox = draw.textbbox((0, 0), gm_text, font=gm_font)
                gm_width = gm_bbox[2] - gm_bbox[0]

            draw.text(
                (x + (table_width - gm_width) // 2, y + GM_NAME_Y_OFFSET),
                gm_text,
                text_color,
                font=gm_font,
            )

            # Players - larger gap after GM name
            players = [p["name"].upper() for p in table.get("approved_players", [])]
            player_y = y + PLAYER_START_Y_OFFSET
            for player in players:
                player_bbox = draw.textbbox((0, 0), player, font=player_font)
                player_width = player_bbox[2] - player_bbox[0]

                # If player name is too long, truncate it with ellipsis
                if player_width > table_width - 20:
                    max_player_chars = int(
                        len(player) * (table_width - 40) / player_width
                    )
                    player = player[: max_player_chars - 3] + "..."
                    player_bbox = draw.textbbox((0, 0), player, font=player_font)
                    player_width = player_bbox[2] - player_bbox[0]

                draw.text(
                    (x + (table_width - player_width) // 2, player_y),
                    player,
                    text_color,
                    font=player_font,
                )
                player_y += PLAYER_SPACING

        current_y += max_height_per_row[row] + TABLE_MARGIN

    return current_y
