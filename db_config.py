import mysql.connector

def db_connection():
    return mysql.connector.connect(
                host="localhost",
                user="root",
                password="Database@123",
                database="whatsapp_ticket"
            )