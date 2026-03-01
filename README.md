# Finventory — Accounting & Inventory Management SaaS

A production-ready, multi-tenant accounting and inventory platform purpose-built for liquor distribution businesses. Handles inventory, POS sales, credit management, expenses, tax calculation (progressive brackets + VAT), and financial reporting.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13 · Django 5.1 · Django REST Framework 3.15 |
| Auth | JWT (SimpleJWT) + token blacklisting + refresh rotation |
| Database | PostgreSQL (primary) · SQLite (tests) |
| Caching | Redis + django-redis |
| Task queue | Celery + Redis broker |
| Frontend | React 18 · Vite 6 · TypeScript · Tailwind CSS 3 |
| State | Zustand (with localStorage persistence) |
| Charts | Recharts |
| Containerisation | Docker + Docker Compose |

---

## Project Structure

```
finventory/
├── backend/
│   ├── apps/
│   │   ├── authentication/   # Custom User model, JWT login/register/logout
│   │   ├── tenancy/          # Organisation, Membership (RBAC), Invitation
│   │   ├── subscriptions/    # Plan, Subscription, PaymentHistory
│   │   ├── inventory/        # Product, Category, Warehouse, Batch, StockItem, StockMovement
│   │   ├── sales/            # Invoice, SaleItem, SalePayment + SaleService
│   │   ├── customers/        # Customer (credit limits, balances)
│   │   ├── credits/          # Credit ledger, aging reports
│   │   ├── expenses/         # Expense / miscellaneous income
│   │   ├── purchases/        # PurchaseOrder, PurchaseItem
│   │   ├── suppliers/        # Supplier management
│   │   ├── tax/              # TaxClass, TaxConfig, TaxBracket, TaxReturn + TaxEngine
│   │   ├── reports/          # P&L, sales trend, top products/customers, cash flow
│   │   └── core/             # Base models (UUID PK, soft-delete, tenant-aware), permissions, mixins
│   ├── config/
│   │   ├── settings/         # base / development / production / testing
│   │   ├── urls.py
│   │   ├── celery.py
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── requirements/
│   │   ├── base.txt
│   │   ├── development.txt
│   │   └── production.txt
│   ├── manage.py
│   └── pytest.ini
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── auth/          # LoginPage, RegisterPage
│   │   │   ├── dashboard/     # DashboardPage (KPI cards, charts)
│   │   │   ├── inventory/     # ProductsPage, StockPage
│   │   │   ├── sales/         # SalesPage (invoice list), NewSalePage (POS)
│   │   │   ├── customers/     # CustomersPage (credit utilisation)
│   │   │   ├── expenses/      # ExpensesPage (income/expense toggle)
│   │   │   └── reports/       # ReportsPage (P&L, area/bar/pie charts)
│   │   ├── components/layout/ # AppLayout, Sidebar, TopBar
│   │   ├── services/api.ts    # Axios client (JWT + tenant header + auto-refresh)
│   │   ├── store/authStore.ts # Zustand auth store
│   │   ├── types/index.ts     # TypeScript interfaces for all domain objects
│   │   └── lib/utils.ts       # formatCurrency, formatDate, getStatusColor, cn
│   ├── package.json
│   └── vite.config.ts         # Dev server proxies /api → localhost:8000
├── tests/                     # Pytest integration + unit tests
│   ├── conftest.py
│   ├── test_auth_api.py
│   ├── test_inventory.py
│   ├── test_sales_api.py
│   └── test_tax_engine.py
├── docker-compose.yml
├── Dockerfile
└── venv/                      # Python virtual environment
```

---

## Quick Start — Local Development

### Prerequisites

- Python 3.11+ (3.13 recommended)
- Node.js 20+
- PostgreSQL 16+ running locally (or use Docker)
- Redis running locally (or use Docker)

---

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd finventory
```

---

### 2. Activate the virtual environment

The virtual environment was created during initial setup and lives in `venv/`.

**Windows (Git Bash / WSL):**
```bash
source venv/Scripts/activate
```

**macOS / Linux:**
```bash
source venv/bin/activate
```

---

### 3. Configure environment variables

Create `backend/.env` (copy from the example below and fill in your values):

```env
# Django
SECRET_KEY=your-secret-key-min-50-chars
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=postgresql://postgres:password@localhost:5432/finventory

# Redis
REDIS_URL=redis://localhost:6379/0

# Email (optional for dev — console backend used by default)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

Generate a secret key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

### 4. Install Python dependencies

```bash
pip install -r backend/requirements/development.txt
```

---

### 5. Set up the database

```bash
cd backend
python manage.py migrate
python manage.py createsuperuser
```

---

### 6. Run the backend

```bash
# From the backend/ directory
python manage.py runserver
```

API is now available at `http://localhost:8000/api/v1/`
API docs (Swagger UI): `http://localhost:8000/api/docs/`

---

### 7. Install and run the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend available at `http://localhost:5173`
The Vite dev server automatically proxies `/api` requests to the Django backend.

---

## Running with Docker

```bash
# Start all services (Postgres, Redis, Django, Celery, React)
docker compose up --build

# Apply migrations
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
```

Services:
- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000/api/v1/`
- Admin: `http://localhost:8000/admin/`

---

## Running Tests

```bash
cd backend
pytest
```

All 27 tests should pass. Tests use SQLite in-memory, so no Postgres needed.

```bash
# With verbose output
pytest -v

# Run specific test file
pytest ../tests/test_tax_engine.py -v
```

---

## API Reference

All endpoints are prefixed with `/api/v1/`.

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/register/` | Register a new user |
| POST | `/auth/login/` | Obtain JWT tokens |
| POST | `/auth/token/refresh/` | Refresh access token |
| POST | `/auth/logout/` | Blacklist refresh token |
| GET | `/auth/profile/` | Current user profile |

### Tenant Headers

Every authenticated request (except `/auth/*`) must include:

```
X-Organisation-ID: <your-org-uuid>
```

### Inventory

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/inventory/products/` | List / create products |
| GET/PATCH | `/inventory/products/{id}/` | Retrieve / update product |
| GET | `/inventory/products/low-stock/` | Products below reorder level |
| GET | `/inventory/products/valuation/` | Stock valuation report |
| GET/POST | `/inventory/stock/` | StockItem list |
| GET | `/inventory/movements/` | Stock movement ledger |

### Sales

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/sales/invoices/` | List / create invoices |
| GET | `/sales/invoices/{id}/` | Invoice detail |
| POST | `/sales/invoices/{id}/pay/` | Record payment |
| POST | `/sales/invoices/{id}/void/` | Void invoice (reverses stock) |

### Reports

| Method | Endpoint | Description |
|---|---|---|
| GET | `/reports/pnl/` | Profit & Loss statement |
| GET | `/reports/sales/` | Sales trend (daily/weekly/monthly) |
| GET | `/reports/top-products/` | Revenue by product |
| GET | `/reports/top-customers/` | Revenue by customer |
| GET | `/reports/cash-flow/` | Cash flow summary |
| GET | `/reports/expenses/` | Expense breakdown by category |

Report endpoints accept `date_from` and `date_to` query params (ISO 8601 dates).

### Tax

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/tax/configs/` | Manage tax configurations |
| POST | `/tax/configs/calculate_income_tax/` | Calculate income tax for an amount |
| POST | `/tax/configs/vat_report/` | VAT collected/payable summary |

---

## Multi-Tenancy & RBAC

Each user can belong to multiple organisations. Every API resource is scoped to the active organisation via the `X-Organisation-ID` header.

**Role hierarchy** (highest → lowest):

| Role | Level | Typical Permissions |
|---|---|---|
| `owner` | 100 | Full access, subscription management |
| `admin` | 80 | All except billing |
| `manager` | 60 | Inventory, sales, staff management |
| `accountant` | 40 | Financials, reports, tax |
| `staff` | 20 | POS sales, stock lookups |
| `viewer` | 10 | Read-only |

---

## Tax Engine

The tax engine supports:

- **Progressive (bracketed) income tax** — Nigeria PIT style with pre-computed cumulative tax per bracket for O(1) lookup
- **Flat rate tax** — single rate applied to entire taxable income
- **VAT / Sales Tax** — applied per product based on `TaxClass`, supports VAT-inclusive price extraction

All tax rates and brackets are stored in the database (`TaxConfig`, `TaxBracket`) — nothing is hardcoded. Each organisation configures its own tax rules per country and year.

```python
# Example: calculate Nigeria PIT
engine = TaxEngine(config)  # config loaded from DB
result = engine.calculate(income=Decimal("2_400_000"), personal_allowance=Decimal("200_000"))
print(result.tax_payable)      # Decimal
print(result.effective_rate)   # e.g., Decimal("12.50")
print(result.bracket_breakdown) # list of dicts per bracket
```

---

## Frontend Pages

| Route | Page | Description |
|---|---|---|
| `/dashboard` | Dashboard | KPI cards, revenue area chart, top-products pie, low-stock alerts |
| `/inventory/products` | Products | Product catalogue with create modal |
| `/inventory/stock` | Stock Levels | Per-warehouse stock with low-stock filter |
| `/sales` | Sales | Invoice list with status/search filters |
| `/sales/new` | New Sale (POS) | Product search, cart, customer selection, payment method |
| `/customers` | Customers | Credit utilisation bars, customer detail drawer |
| `/expenses` | Expenses & Income | Toggle income/expense, category breakdown |
| `/reports` | Reports | P&L cards, area/bar/pie charts, top-customer table |

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | Yes | — | Django secret key |
| `DEBUG` | No | `False` | Enable debug mode |
| `ALLOWED_HOSTS` | Yes | — | Comma-separated hostnames |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `REDIS_URL` | Yes | — | Redis connection string |
| `EMAIL_BACKEND` | No | console | Django email backend |
| `CORS_ALLOWED_ORIGINS` | No | localhost | Allowed CORS origins |
| `JWT_ACCESS_TOKEN_LIFETIME_MINUTES` | No | `60` | Access token TTL |
| `JWT_REFRESH_TOKEN_LIFETIME_DAYS` | No | `7` | Refresh token TTL |

---

## Architecture Notes

**Two-phase tenant resolution** — Django middleware runs before DRF JWT authentication. To avoid a circular dependency, tenant resolution is split:
1. `TenantMiddleware` captures `request._raw_org_id` from the `X-Organisation-ID` header
2. `TenantFilterMixin` (in views, post-DRF-auth) calls `resolve_organisation()` which validates membership and sets `request.organisation`

**Immutable stock ledger** — `StockMovement` is append-only. `StockItem` holds the denormalised current balance for O(1) reads. All mutations use `select_for_update()` inside atomic transactions to prevent race conditions.

**Soft deletes** — No records are ever physically deleted. `SoftDeleteModel` sets `is_deleted=True` and `deleted_at`. The default manager filters these out automatically.

**Service layer** — Business logic lives in `services.py` per app (e.g., `SaleService`, `InventoryService`), keeping views thin and logic testable without HTTP.
