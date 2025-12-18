# Pang Dashboard

A Next.js dashboard for viewing and analyzing company data from the Pang pipeline.

## Features

- 🔐 Password-protected access
- 📊 View company data from date folders
- 👥 Browse board members and people data
- 📈 Statistics and overview
- 🎨 Beautiful M.O.N.K.Y dashboard template

## Setup

1. Install dependencies:
```bash
cd 10_jocke/dashboard
npm install
# or
pnpm install
```

2. Set up environment (optional):
Create a `.env.local` file if needed.

3. Run development server:
```bash
npm run dev
# or
pnpm dev
```

4. Open [http://localhost:3000](http://localhost:3000)

## Authentication

Default password: `pang2024`

You can change this in `lib/auth.ts` by updating the `verifyPassword` function.

## Data Structure

The dashboard reads data from `10_jocke/[YYYYMMDD]/` folders:
- `kungorelser_[date].xlsx` - Main company data
- `jocke.xlsx` - Processed board member data (if available)

## API Routes

- `/api/auth/login` - Login endpoint
- `/api/auth/logout` - Logout endpoint
- `/api/data/dates` - Get list of available date folders
- `/api/data/[date]` - Get data for specific date

## Pages

- `/` - Dashboard overview with stats and date folders
- `/login` - Login page
- `/date/[date]` - Detailed view for a specific date

## Build

```bash
npm run build
npm start
```

