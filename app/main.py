"""
Main FastAPI application entry point.
PMS Portal - Performance Management System
"""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.database import init_database
from app.templates_config import templates
from app.routes import auth_routes, dashboard_routes, assignment_routes, revenue_routes, mis_routes, data_routes, admin_routes, approval_routes, enquiry_routes, proposal_request_routes, proposal_routes, finance_routes, training_routes, non_revenue_routes, profile_routes

# Create FastAPI app
app = FastAPI(
    title="PMS Portal",
    description="Officer-wise Performance & Revenue Sharing Portal",
    version="1.0.0"
)

# Setup static files
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scripts.init_db import init_database as full_init
    full_init()


# Root redirect
@app.get("/")
async def root():
    return RedirectResponse(url="/login", status_code=302)


# Include route modules
app.include_router(auth_routes.router, tags=["Authentication"])
app.include_router(dashboard_routes.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(assignment_routes.router, prefix="/assignment", tags=["Assignments"])
app.include_router(revenue_routes.router, prefix="/revenue", tags=["Revenue Sharing"])
app.include_router(mis_routes.router, prefix="/mis", tags=["MIS Analytics"])
app.include_router(data_routes.router, prefix="/data", tags=["Data Management"])
app.include_router(admin_routes.router, prefix="/admin", tags=["Admin"])
app.include_router(approval_routes.router, prefix="/approvals", tags=["Approvals"])
app.include_router(enquiry_routes.router, tags=["Enquiry Management"])
app.include_router(proposal_request_routes.router, tags=["Proposal Request Management"])
app.include_router(proposal_routes.router, tags=["Proposal Management"])
app.include_router(finance_routes.router, prefix="/finance", tags=["Finance & Invoicing"])
app.include_router(training_routes.router, prefix="/training", tags=["Training Programmes"])
app.include_router(non_revenue_routes.router, tags=["Non-Revenue Activities"])
app.include_router(profile_routes.router, tags=["User Profile"])


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error_code": 404, "error_message": "Page not found"},
        status_code=404
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error_code": 500, "error_message": "Internal server error"},
        status_code=500
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
