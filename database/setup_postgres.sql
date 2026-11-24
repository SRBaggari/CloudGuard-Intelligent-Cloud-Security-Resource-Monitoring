-- Create the CloudGuard database and an application role in an existing PostgreSQL server.
-- Run as a superuser, e.g.:
--   psql -U postgres -v app_password="'choose-a-strong-password'" -f database/setup_postgres.sql
-- Then set in backend/.env:
--   DATABASE_URL=postgresql+psycopg://cloudguard:<password>@localhost:5432/cloudguard
-- Tables are created by Alembic migrations when the backend starts (AUTO_MIGRATE=true),
-- or manually with:  cd backend && alembic upgrade head

CREATE ROLE cloudguard WITH LOGIN PASSWORD :app_password;
CREATE DATABASE cloudguard OWNER cloudguard ENCODING 'UTF8';
REVOKE ALL ON DATABASE cloudguard FROM PUBLIC;
GRANT CONNECT ON DATABASE cloudguard TO cloudguard;
