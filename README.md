# Local AI Business Card Scanner

A lightweight, secure Django application that scans business cards using Gemini AI, extracts key contact information, and archives records along with original card images and user-defined notes in a local SQLite database.

## Features

* **AI Extraction:** Automatically extracts first name, last name, company name, email, and phone number from business card images using the Gemini 2.5 Flash model.
* **Network Resilient:** Bypasses proxy or strict corporate firewall blocks by utilizing native HTTP routing directly to the API endpoint.
* **Local Storage:** Securely logs extracted contact fields, physical card images, custom manual notes, and timestamps locally.
* **Interactive Dashboard:** Dynamic interface to review, sort, and display archived cards with full image access.

## Tech Stack

* **Backend Framework:** Django 5.1.5
* **Language:** Python 3.12
* **Database:** SQLite3
* **AI Integration:** Google Gemini API (v1beta endpoint via raw HTTP requests)

## Setup Instructions

### 1. Clone and Navigate

```bash
git clone [https://github.com/Rehansh26/MSTinternship-Rehansh-Shrivastava.git](https://github.com/Rehansh26/MSTinternship-Rehansh-Shrivastava.git)
cd MSTinternship-Rehansh-Shrivastava
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment Variables

Create a file named `.env` in the root directory (same level as `manage.py`) and add your Gemini API key:

```env
GEMINI_API_KEY="YOUR_ACTUAL_API_KEY_HERE"
```

### 4. Database Setup

Initialize the database schemas and run the migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

### 5. Running the Application

Start the development server:

```bash
python manage.py runserver
```

Open your browser and navigate to:
* **Scanner Home:** http://127.0.0.1:8000/
* **Saved Cards Dashboard:** http://127.0.0.1:8000/dashboard/

---

## Deployment on Google Cloud VM

When running this on a production Google Cloud Compute Engine VM environment:

1. Clone the repository onto the VM instance.
2. Ensure Python 3.10+ and pip are installed on the host.
3. Install dependencies: 
   ```bash
   pip install -r requirements.txt
   
```
4. Manually construct the `.env` file containing the `GEMINI_API_KEY` directly in the root path.
5. Run migrations: 
   ```bash
   python manage.py migrate
   
```
6. Expose the Django port on your VM firewall settings or set up a reverse proxy (like Nginx), then boot the app binding the network interfaces:
   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```