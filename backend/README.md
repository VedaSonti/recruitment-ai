# iSOFT Recruitment AI

AI-powered recruitment platform that matches CVs against job descriptions using OpenAI embeddings and GPT reasoning.

## Architecture

- **Backend**: FastAPI on Render
- **Frontend**: Next.js (App Router, TypeScript, Tailwind CSS)
- **Database**: MongoDB Atlas (free M0 tier)
- **Vector Search**: MongoDB Atlas Vector Search (`autoembed_index` on `candidates` and `jobs` collections)
- **AI**: OpenAI `gpt-4o-mini` for parsing, `gpt-4o` for analysis, `text-embedding-3-small` for embeddings

## MongoDB Collections

- `recruiters` — recruiter accounts
- `clients` — client companies
- `jobs` — parsed job descriptions with embeddings
- `candidates` — parsed CVs with embeddings
- `matches` — all-to-all match records with scores, status, and cached analysis
- `generated_profiles` — GPT-uplifted candidate profiles
- `interviews` — AI interview sessions (future feature)

## Pipeline Status

`Uploaded → Matched → Approved → Shortlisted → Interview Sent → Interview Completed → Uplifted → Sent`

## Backend Setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Fill in OPENAI_API_KEY and MONGODB_URI in .env
uvicorn main:app --reload
```

API docs at: http://127.0.0.1:8000/docs

## Frontend Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
# Fill in NEXT_PUBLIC_API_URL in .env.local
npm run dev
```

App at: http://localhost:3000

## Atlas Vector Search Index

Required on both `candidates` and `jobs` collections:
- Index name: `autoembed_index`
- Field: `embedding`
- Dimensions: 1536
- Similarity: cosine

## Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /jobs/upload | Upload JD file, parse, embed, match |
| POST | /candidates/upload | Upload CV file, parse, embed, match |
| GET | /jobs | List all jobs |
| GET | /jobs/{id} | Single job detail |
| GET | /candidates | List all candidates |
| GET | /candidates/{id} | Single candidate detail |
| GET | /matches/by-job/{id} | Ranked candidates for a job |
| GET | /matches/by-candidate/{id} | Ranked jobs for a candidate |
| GET | /matches/{id} | Single match detail |
| GET | /matches/{id}/skill-analysis | Semantic skill matching |
| POST | /matches/{id}/analyse | GPT decision intelligence |
| POST | /matches/analyse-top/{job_id} | Batch analyse top N candidates |
| PATCH | /matches/{id}/status | Update pipeline status |
