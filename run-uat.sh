#!/bin/bash
# =============================================================================
# PMS Portal — Automated UAT Script (Rule 8: Test via API Script)
# Tests every critical endpoint via HTTP requests.
# Run: bash run-uat.sh [base_url]
# =============================================================================

BASE_URL="${1:-http://localhost:8000}"
PASSED=0
FAILED=0
TOTAL=0
COOKIE_JAR="/tmp/pms_uat_cookies.txt"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

test_endpoint() {
    local method="$1"
    local path="$2"
    local expected_status="$3"
    local description="$4"
    local data="$5"
    TOTAL=$((TOTAL + 1))

    if [ "$method" = "GET" ]; then
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -L "$BASE_URL$path")
    else
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -c "$COOKIE_JAR" -L -X POST -d "$data" "$BASE_URL$path")
    fi

    if [ "$STATUS" = "$expected_status" ]; then
        echo -e "  ${GREEN}PASS${NC} [$STATUS] $method $path — $description"
        PASSED=$((PASSED + 1))
    else
        echo -e "  ${RED}FAIL${NC} [$STATUS expected $expected_status] $method $path — $description"
        FAILED=$((FAILED + 1))
    fi
}

echo "============================================================"
echo "PMS Portal — Automated UAT"
echo "Base URL: $BASE_URL"
echo "============================================================"
echo ""

# --- Health Check ---
echo -e "${YELLOW}1. Health Check${NC}"
test_endpoint GET "/health/" "200" "Health check returns OK"

# --- Authentication ---
echo -e "\n${YELLOW}2. Authentication${NC}"
test_endpoint GET "/login/" "200" "Login page loads"
test_endpoint GET "/" "200" "Root redirects to login (or dashboard)"

# Login as admin
echo "  Logging in as admin..."
curl -s -c "$COOKIE_JAR" -L -X POST \
    -d "email=admin@npcindia.gov.in&password=admin123&csrfmiddlewaretoken=test" \
    "$BASE_URL/login/" > /dev/null 2>&1
# Get CSRF token first
CSRF=$(curl -s -c "$COOKIE_JAR" -b "$COOKIE_JAR" "$BASE_URL/login/" | grep -o 'csrfmiddlewaretoken.*value="[^"]*"' | head -1 | grep -o '"[^"]*"$' | tr -d '"')
curl -s -c "$COOKIE_JAR" -b "$COOKIE_JAR" -L -X POST \
    -d "email=admin@npcindia.gov.in&password=admin123&csrfmiddlewaretoken=$CSRF" \
    -H "Referer: $BASE_URL/login/" \
    "$BASE_URL/login/" > /dev/null 2>&1

# --- Dashboard ---
echo -e "\n${YELLOW}3. Dashboard${NC}"
test_endpoint GET "/dashboard/" "200" "Dashboard loads"
test_endpoint GET "/dashboard/summary/" "200" "Dashboard summary loads"

# --- Assignments ---
echo -e "\n${YELLOW}4. Assignments${NC}"
test_endpoint GET "/assignment/register/" "200" "Register activity page loads"
test_endpoint GET "/assignment/workorders/" "200" "Work orders list loads"
test_endpoint GET "/assignment/select-activity-type/" "200" "Select activity type loads"
test_endpoint GET "/mis/assignments/" "200" "Assignments list (MIS) loads"

# --- Approvals ---
echo -e "\n${YELLOW}5. Approvals${NC}"
test_endpoint GET "/approvals/" "200" "Approvals page loads"

# --- Finance ---
echo -e "\n${YELLOW}6. Finance${NC}"
test_endpoint GET "/finance/" "200" "Finance dashboard loads"

# --- MIS ---
echo -e "\n${YELLOW}7. MIS Analytics${NC}"
test_endpoint GET "/mis/" "200" "MIS command center loads"
test_endpoint GET "/mis/export/csv/" "200" "MIS CSV export works"

# --- Clients ---
echo -e "\n${YELLOW}8. Clients${NC}"
test_endpoint GET "/clients/" "200" "Client list loads"
test_endpoint GET "/clients/new/" "200" "New client form loads"
test_endpoint GET "/clients/mis/" "200" "Client MIS loads"

# --- Training ---
echo -e "\n${YELLOW}9. Training${NC}"
test_endpoint GET "/training/" "200" "Training list loads"
test_endpoint GET "/training/create/" "200" "Training create form loads"

# --- Utilization ---
echo -e "\n${YELLOW}10. Utilization${NC}"
test_endpoint GET "/utilization/" "200" "Utilization list loads"
test_endpoint GET "/utilization/new/" "200" "New claim form loads"
test_endpoint GET "/utilization/summary/" "200" "Utilization summary loads"

# --- Reports ---
echo -e "\n${YELLOW}11. Reports${NC}"
test_endpoint GET "/reports/delays/" "200" "Delay dashboard loads"
test_endpoint GET "/reports/physical-progress/" "200" "Physical progress loads"
test_endpoint GET "/reports/financial-progress/" "200" "Financial progress loads"
test_endpoint GET "/reports/delays/api/summary/" "200" "Delay summary API works"

# --- Proposals ---
echo -e "\n${YELLOW}12. Proposals${NC}"
test_endpoint GET "/proposals/" "200" "Proposal list loads"

# --- Non-Revenue ---
echo -e "\n${YELLOW}13. Development Work${NC}"
test_endpoint GET "/non-revenue/" "200" "Development work list loads"
test_endpoint GET "/non-revenue/create/" "200" "Create suggestion form loads"

# --- Profile ---
echo -e "\n${YELLOW}14. Profile${NC}"
test_endpoint GET "/profile/" "200" "Profile page loads"
test_endpoint GET "/profile/change-password/" "200" "Change password form loads"

# --- Admin ---
echo -e "\n${YELLOW}15. Admin${NC}"
test_endpoint GET "/admin-panel/users/" "200" "User management loads"
test_endpoint GET "/admin-panel/roles/" "200" "Role management loads"
test_endpoint GET "/data/export/" "200" "Data export page loads"
test_endpoint GET "/data/admin/config/" "200" "Config page loads"

# --- Django Admin ---
echo -e "\n${YELLOW}16. Django Admin Panel${NC}"
test_endpoint GET "/admin/" "200" "Django admin loads"

# --- API Endpoints ---
echo -e "\n${YELLOW}17. API Endpoints${NC}"
test_endpoint GET "/data/api/subdomains/ES/" "200" "Subdomains API works"
test_endpoint GET "/revenue/api/officers/" "200" "Officers API works"

# --- Logout ---
echo -e "\n${YELLOW}18. Logout${NC}"
test_endpoint GET "/logout/" "200" "Logout redirects to login"

# --- Summary ---
echo ""
echo "============================================================"
echo -e "UAT Results: ${GREEN}$PASSED passed${NC}, ${RED}$FAILED failed${NC}, $TOTAL total"
echo "============================================================"

# Cleanup
rm -f "$COOKIE_JAR"

if [ "$FAILED" -gt 0 ]; then
    exit 1
else
    echo -e "${GREEN}All UAT tests passed!${NC}"
    exit 0
fi
