import re
import json
from httplib2 import Http
from bot import LOGGER, G_DRIVE_CLIENT_ID, G_DRIVE_CLIENT_SECRET
from bot.config import Messages
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from bot.helpers.sql_helper import gDriveDB
from bot.config import BotCommands
from bot.helpers.utils import CustomFilters

# OAuth 2.0 scope for Google Drive
OAUTH_SCOPE = ["https://www.googleapis.com/auth/drive"]
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

flow = None
user_flows = {}  # Store flows per user

@Client.on_message(filters.private & filters.incoming & filters.command(BotCommands.Authorize))
async def _auth(client, message):
    user_id = message.from_user.id
    creds = gDriveDB.search(user_id)
    if creds is not None:
        try:
            if hasattr(creds, 'expired') and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            gDriveDB._set(user_id, creds)
            await message.reply_text(Messages.ALREADY_AUTH, quote=True)
        except Exception as e:
            LOGGER.error(f"Error refreshing credentials: {e}")
            await message.reply_text(f"**ERROR:** `{e}`", quote=True)
    else:
        try:
            # Create OAuth 2.0 flow
            client_config = {
                "installed": {
                    "client_id": G_DRIVE_CLIENT_ID,
                    "client_secret": G_DRIVE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": [REDIRECT_URI]
                }
            }
            
            user_flow = Flow.from_client_config(
                client_config,
                scopes=OAUTH_SCOPE,
                redirect_uri=REDIRECT_URI
            )
            
            # Generate authorization URL with offline access
            auth_url, state = user_flow.authorization_url(
                access_type='offline',
                prompt='consent'
            )
            
            # Store flow for this user
            user_flows[user_id] = user_flow
            
            LOGGER.info(f'AuthURL:{user_id}')
            await message.reply_text(
                text=Messages.AUTH_TEXT.format(auth_url),
                quote=True,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Authorization URL", url=auth_url)]]
                )
            )
        except Exception as e:
            LOGGER.error(f"Authorization error: {e}")
            await message.reply_text(f"**ERROR:** `{e}`", quote=True)


@Client.on_message(filters.private & filters.incoming & filters.command(BotCommands.Revoke) & CustomFilters.auth_users)
def _revoke(client, message):
    user_id = message.from_user.id
    try:
        gDriveDB._clear(user_id)
        # Clear user flow if exists
        if user_id in user_flows:
            del user_flows[user_id]
        LOGGER.info(f'Revoked:{user_id}')
        message.reply_text(Messages.REVOKED, quote=True)
    except Exception as e:
        message.reply_text(f"**ERROR:** `{e}`", quote=True)


@Client.on_message(filters.private & filters.incoming & filters.text & ~CustomFilters.auth_users)
async def _token(client, message):
    token = message.text.split()[-1]
    WORD = len(token)
    if WORD == 62 and token[1] == "/":
        creds = None
        user_id = message.from_user.id
        
        if user_id in user_flows:
            try:
                sent_message = await message.reply_text("**Checking received code...**", quote=True)
                user_flow = user_flows[user_id]
                
                # Exchange authorization code for credentials
                user_flow.fetch_token(authorization_response=message.text)
                creds = user_flow.credentials
                
                gDriveDB._set(user_id, creds)
                LOGGER.info(f'AuthSuccess: {user_id}')
                await sent_message.edit(Messages.AUTH_SUCCESSFULLY)
                
                # Clean up flow
                del user_flows[user_id]
            except ValueError as e:
                LOGGER.error(f"Invalid authorization code: {e}")
                if 'sent_message' in locals():
                    await sent_message.edit(Messages.INVALID_AUTH_CODE)
                else:
                    await message.reply_text(Messages.INVALID_AUTH_CODE, quote=True)
            except Exception as e:
                LOGGER.error(f"Token exchange error: {e}")
                if 'sent_message' in locals():
                    await sent_message.edit(f"**ERROR:** `{str(e)}`")
                else:
                    await message.reply_text(f"**ERROR:** `{str(e)}`", quote=True)
        else:
            await message.reply_text(Messages.FLOW_IS_NONE, quote=True)
