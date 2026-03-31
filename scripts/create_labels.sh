#!/usr/bin/env bash
set -e
REPO="auzvolt/wem-energy-cost-model"

create_label() {
  local name="$1" color="$2" desc="$3"
  gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" 2>/dev/null \
    || gh label edit "$name" --repo "$REPO" --color "$color" --description "$desc" 2>/dev/null \
    || echo "SKIP: $name"
}

create_label "epic:discovery"           "7c3aed" "Phase 1: Discovery & Data Architecture"
create_label "epic:data-pipeline"       "2563eb" "Phase 2: WEM Market Data Pipeline"
create_label "epic:optimisation"        "059669" "Phase 3: Simulation & Optimisation Engine"
create_label "epic:assumption-library"  "d97706" "Phase 4: Asset & Assumption Library"
create_label "epic:financial-model"     "dc2626" "Phase 5: Commercial & Financial Modelling"
create_label "epic:streamlit-app"       "7c3aed" "Phase 6: Streamlit Application & Dashboard"
create_label "epic:testing-deployment"  "374151" "Phase 7: Testing, Validation & Deployment"

echo "All epic labels created."
