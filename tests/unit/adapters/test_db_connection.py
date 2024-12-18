import os

# Load environment variables (if using a .env file)
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

# Get the database URL from environment variables
DATABASE_URL = os.getenv("DATABASE_URL")


def test_connection():
    try:
        # Create a new SQLAlchemy engine
        engine = create_engine(DATABASE_URL)

        # Connect to the database
        with engine.connect() as connection:
            print("Connection to the database was successful!")
            # Optionally, you can execute a simple query to test
            result = connection.execute("SELECT 1")
            for row in result:
                print(row)
    except SQLAlchemyError as e:
        print(f"Error connecting to the database: {e}")


if __name__ == "__main__":
    test_connection()
