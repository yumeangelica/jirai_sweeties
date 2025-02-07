FROM python:3.12-slim

WORKDIR /app

# update and install sqlite3
RUN apt update && apt install -y sqlite3 libsqlite3-dev

# Copy the dependencies file to the working directory
COPY requirements.txt /app

# Installs the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# COPY <source> <destination>
COPY . /app

# Set the command to run on container start (e.g. 'main.py')
CMD ["python", "run.py"]
