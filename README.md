# Gym Agent

A private Telegram personal trainer that remembers your profile and lifting history, logs sets,
shows estimated progress, and uses OpenAI for context-aware workout suggestions and coaching.

## What it does

- Stores profiles, workouts, sets, progression feedback, and plans in Google Cloud Firestore.
- Suggests workouts from your goals, constraints, schedule, equipment, and recent sessions.
- Accepts concise gym-floor logging such as `/log Squat 225x5@8, Squat 225x5@8.5`.
- Restricts access to one Telegram user when `ALLOWED_TELEGRAM_USER_ID` is configured.
- Sends the profile, recent sets, and progression guidance to OpenAI when coaching.

This is a coaching aid, not medical care. Stop training and seek appropriate medical help for
chest pain, fainting, severe shortness of breath, or an acute injury.

## Setup

1. In Telegram, message `@BotFather`, run `/newbot`, and copy the bot token.
2. Create a Python 3.11+ virtual environment and install the project:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e '.[dev]'
   ```

3. Install the Google Cloud CLI, select a project with a Firestore Native database, and configure
   local Application Default Credentials:

   ~~~bash
   gcloud auth application-default login
   gcloud config set project YOUR_PROJECT_ID
   ~~~

4. Copy .env.example to .env, add your Telegram token and OpenAI API key, set
   GOOGLE_CLOUD_PROJECT, and leave WEBHOOK_URL blank for local polling.
5. Initially leave ALLOWED_TELEGRAM_USER_ID empty. Start the bot and send /whoami:

   ```bash
   gym-agent
   ```

6. Stop it, put the returned ID in .env, and restart. This makes the bot private.
7. Send /start, save your /profile, then use /workout or chat naturally.

## Commands

```text
/profile goals=strength; experience=intermediate; schedule=4 days; equipment=full gym; limitations=none; units=lb
/workout
/plan
/log Bench Press 185x5@8, Bench Press 185x5@8.5
/feedback Bench Press increase - all sets felt strong
/history
/progress
```

`/workout` creates and saves a goal-aware session. At the gym, `/plan` recalls it. After logging
an exercise, use `/feedback Exercise increase`, `same`, or `decrease`; the bot stores that choice
and applies a conservative 5 lb or 2.5 kg adjustment when recommending the exercise next time.

Local execution uses long polling. Cloud Run uses an HTTPS webhook.

## Deploy to Google Cloud Run

The deployment is configured for project gym-trainer-502823 in us-east4:

~~~bash
PROJECT_ID=gym-trainer-502823
REGION=us-east4
SERVICE=gym-trainer
SERVICE_ACCOUNT=gym-trainer-runner
~~~

Enable the APIs and create the default Firestore Native database if it does not already exist:

~~~bash
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com firestore.googleapis.com secretmanager.googleapis.com
gcloud firestore databases create --database="(default)" --location="$REGION" --type=firestore-native
~~~

Create a dedicated runtime identity and grant only Firestore access:

~~~bash
gcloud iam service-accounts create "$SERVICE_ACCOUNT"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SERVICE_ACCOUNT@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
~~~

Create three Secret Manager secrets and add their values through standard input:

~~~bash
gcloud secrets create telegram-bot-token --replication-policy=automatic
gcloud secrets versions add telegram-bot-token --data-file=-
gcloud secrets create openai-api-key --replication-policy=automatic
gcloud secrets versions add openai-api-key --data-file=-
gcloud secrets create telegram-webhook-secret --replication-policy=automatic
gcloud secrets versions add telegram-webhook-secret --data-file=-
~~~

The webhook secret must contain only letters, numbers, underscores, or hyphens. Grant the runtime
identity access to each secret:

~~~bash
for SECRET in telegram-bot-token openai-api-key telegram-webhook-secret; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:$SERVICE_ACCOUNT@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
~~~

Deploy once to create the service and obtain its URL:

~~~bash
gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --service-account="$SERVICE_ACCOUNT@$PROJECT_ID.iam.gserviceaccount.com" \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,FIRESTORE_DATABASE=(default)" \
  --set-secrets="TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,OPENAI_API_KEY=openai-api-key:latest,TELEGRAM_WEBHOOK_SECRET=telegram-webhook-secret:latest"

SERVICE_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" \
  --format='value(status.url)')"
~~~

Then configure the assigned URL. This deploys a new revision, which registers the authenticated
SERVICE_URL/telegram webhook with Telegram:

~~~bash
gcloud run services update "$SERVICE" --region "$REGION" \
  --update-env-vars="WEBHOOK_URL=$SERVICE_URL"
~~~

Verify the service:

~~~bash
curl "$SERVICE_URL/health"
~~~

Cloud Run must allow unauthenticated ingress because Telegram cannot attach Google IAM
credentials. Requests to the Telegram endpoint are separately authenticated with the
X-Telegram-Bot-Api-Secret-Token header.

## Development

```bash
pytest
ruff check .
```
