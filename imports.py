import os
from datetime import datetime, timedelta, timezone, time
from dotenv import load_dotenv
load_dotenv()
import requests
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, CallbackContext
)
from PIL import Image
import pytesseract
from io import BytesIO
import uvicorn