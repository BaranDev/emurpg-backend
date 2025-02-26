from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from pymongo.database import Database


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

    # Image dimensions and colors
    WIDTH = 1920
    HEIGHT = max(1080, 600 + (len(tables) * 200))  # Base height plus 200px per table
    BACKGROUND = (44, 24, 16)  # Deep brown
    BORDER_COLOR = (139, 69, 19)  # Saddle brown
    TEXT_COLOR = (255, 215, 0)  # Gold
    HEADER_COLOR = (255, 223, 0)  # Bright gold
    TABLE_BG = (59, 36, 23)  # Darker brown

    def calculate_table_height(table):
        num_players = len(table.get("approved_players", []))
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

            # Players - Changed to use approved_players instead of joined_players
            players = [p["name"].upper() for p in table.get("approved_players", [])]
            player_y = y + 200
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
