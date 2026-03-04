
  ------------------------------------------------------------------------------------------------------------------------------------------------------------

  🗄️ Backend (DB + Redis + Workers)

   # From repo root
   cd backend
   docker-compose up --build

  This starts PostgreSQL, Redis Stack, and the Python workers together.

  To run only the database (PostgreSQL + Redis, no workers):

   cd backend
   docker-compose up postgres redis-stack

  ------------------------------------------------------------------------------------------------------------------------------------------------------------   

  🖥️ Frontend (Shopify App)

   # From repo root

   # First time only - install deps & run DB migrations:
   npm install
   npm run setup

   # Start dev server:
   npm run dev

  ------------------------------------------------------------------------------------------------------------------------------------------------------------   

  Summary

  ┌───────────────┬──────────────────────────────────────────────────────┐
  │ Service       │ Command                                              │
  ├───────────────┼──────────────────────────────────────────────────────┤
  │ Backend (all) │ cd backend && docker-compose up --build              │
  ├───────────────┼──────────────────────────────────────────────────────┤
  │ DB only       │ cd backend && docker-compose up postgres redis-stack │
  ├───────────────┼──────────────────────────────────────────────────────┤
  │ Frontend dev  │ npm run dev (from root)                              │
  ├───────────────┼──────────────────────────────────────────────────────┤
  │ Frontend prod │ npm run build && npm run start                       │
  └───────────────┴──────────────────────────────────────────────────────┘
