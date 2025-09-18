import os
import json
import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore
from google.oauth2 import service_account

ENVIRONMENT = os.getenv("ENVIRONMENT", "local") 

if ENVIRONMENT == "production":
    service_account_info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred)

    firestore_credentials = service_account.Credentials.from_service_account_info(service_account_info)

else:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

    firestore_credentials = service_account.Credentials.from_service_account_file("serviceAccountKey.json")

db = firestore.Client(credentials=firestore_credentials)
