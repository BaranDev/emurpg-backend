# EMU RPG API

API is hosted on https://api.emurpg.com

## Overview

The EMU RPG API is a backend service designed to support the EMU RPG Club's events and activities. It provides various functionalities to manage game tables, players, and character sheets for Dungeons & Dragons (D&D) games.

## Functionalities

- **Table Management**: Create, update, and delete game tables. Each table includes details such as game name, game master, player quota, and joined players.
- **Player Management**: Add, update, and remove players from tables. Retrieve player lists for specific tables.
- **Character Sheet Processing**: Upload and process D&D character sheet PDFs to generate a modified roll list, including basic stats, skills, saving throws, weapon attacks, spell attacks, and special abilities.
- **Medieval-Themed Table Layout**: Generate medieval-themed table layouts from a list of employees or players, visualized as images.
- **Real-Time Updates**: Use WebSockets for live communication between the server and clients, providing real-time updates on game tables and player data.
- **API Monitoring**: Monitor and analyze API usage and performance with Moesif Middleware.
- **Data Validation**: Validate data structures and manage settings efficiently using Pydantic.
- **Security**: Secure endpoints with API key validation and origin checks.
- **Cross-Origin Resource Sharing (CORS)**: Implement CORS policies to ensure secure access to the API from different origins.
- **Admin Account Management**: Create and manage admin accounts, including credential checks.
- **Table Layout Generation**: Generate medieval-themed tables from an uploaded CSV file.
- **Character Roller**: Process D&D character sheet PDFs and generate a modified roll list.

By incorporating these functionalities, the EMU RPG API supports the dynamic needs of the EMU RPG Club's events and activities.

## Methodologies

- **RESTful API**: The API adheres to REST principles, offering clear and consistent endpoints for various operations.
- **Asynchronous Programming**: Uses asynchronous programming to manage multiple requests efficiently.
- **Error Handling**: Implements error handling to ensure reliable and predictable API behavior.
- **WebSocket Communication**: Implements WebSocket connections for real-time updates on game tables and player data.
- **API Monitoring**: Uses Moesif Middleware for monitoring and analyzing API usage and performance.
- **Data Validation**: Uses Pydantic for validating data structures and managing settings efficiently.
- **Cross-Origin Resource Sharing (CORS)**: Implements CORS policies to ensure secure access to the API from different origins.
- **Security**: Includes API key validation and origin checks to secure endpoints.

## Technologies and Libraries

The EMU RPG API uses various modern technologies and libraries to deliver a secure and efficient backend service. Below is an overview of the key technologies and their usage:

- **FastAPI**: A high-performance web framework used to build the API, chosen for its speed and efficiency. It uses Python 3.7+ type hints for automatic validation and documentation.
- **MongoDB**: A NoSQL database that stores game tables, players, and admin credentials. It handles dynamic data structures required by the API.
- **PyPDF2**: A library for reading and manipulating PDF files, used to extract text from D&D character sheet PDFs and generate roll lists.
- **Matplotlib**: A plotting library used to create medieval-themed table layouts, visualizing player and table information.
- **OpenAI**: Utilized for processing character sheet data and generating roll lists. The API integrates with OpenAI's models to analyze and extend the base D&D character roll list.
- **Uvicorn**: An ASGI server that serves the FastAPI application, known for its speed and lightweight nature.
- **Pydantic**: Used for data validation and settings management, ensuring data structures are validated and managed efficiently.
- **Moesif Middleware**: Integrated for API monitoring and analytics, providing insights into API usage and helping to monitor performance.
- **CORS Middleware**: Handles Cross-Origin Resource Sharing (CORS) policies, ensuring secure access to the API from different origins.
- **Meta-Llama-3-8B-Instruct**: This LLM processes character sheet PDFs and generates a modified roll list, including all necessary stats, skills, and abilities.
- **WebSockets**: Used for real-time updates, enabling live communication between the server and clients for table and player data.

By combining these technologies and libraries, the EMU RPG API delivers a powerful and efficient backend service that meets the needs of the EMU RPG Club's events and activities.

## API Endpoints

### Admin Endpoints
- **Table Management**:
    - `POST /api/admin/create_table`: Create a new game table.
    - `PUT /api/admin/update_table/{slug}`: Update an existing game table.
    - `DELETE /api/admin/delete_table/{slug}`: Delete a game table.
    - `GET /api/admin/tables`: Retrieve all game tables.
    - `GET /api/admin/table/{slug}`: Get the table details using the provided slug.
- **Player Management**:
    - `POST /api/admin/add_player/{slug}`: Add a new player to a table.
    - `PUT /api/admin/update_player/{slug}/{student_id}`: Update player details.
    - `DELETE /api/admin/delete_player/{slug}/{student_id}`: Remove a player from a table.
    - `GET /api/admin/get_players/{slug}`: Get the list of players for a table.
- **Admin Account Management**:
    - `POST /api/admin/create_admin`: Create a new admin account.
    - `POST /api/admin/checkcredentials`: Check admin credentials.

### User Endpoints
- **Table Endpoints**:
    - `GET /api/tables`: Retrieve all game tables without sensitive data.
    - `GET /api/table/{slug}`: Get the table details using the provided slug without sensitive data.
    - `POST /api/register/{slug}`: Register a player for a table.

### Helper Endpoints
- **Table Layout**:
    - `POST /api/admin/generate-tables`: Generate medieval-themed tables from an uploaded CSV file.

### Character Roller Endpoints
- **Character Sheet Processing**:
    - `POST /api/charroller/process`: Process a D&D character sheet PDF and generate a modified roll list.

## Conclusion

The EMU RPG API is a backend service that uses modern technologies and methodologies to support the dynamic needs of the EMU RPG Club's website. It provides essential functionalities for managing game events, players, and character sheets, ensuring a seamless experience for both game masters and players.


![GitHub release (latest by date)](https://img.shields.io/github/v/release/barandev/emurpg-backend?style=for-the-badge)
![GitHub License](https://img.shields.io/github/license/barandev/emurpg-backend?style=for-the-badge)
![GitHub last commit](https://img.shields.io/github/last-commit/barandev/emurpg-backend?style=for-the-badge)