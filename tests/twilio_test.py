# Download the helper library from https://www.twilio.com/docs/python/install
import os
from twilio.rest import Client

# Find your Account SID and Auth Token at twilio.com/console
# and set the environment variables. See http://twil.io/secure
account_sid = os.environ["TWILIO_ACCOUNT_SID"] #for security i will use api keys in production.
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
client = Client(account_sid, auth_token)

call = client.calls.create(
    url="https://webhooks.twilio.com/v1/Voice/Template/voice_auto_response",
    to="+15719778953",
    from_="+14783775348"
)

print(call.sid)