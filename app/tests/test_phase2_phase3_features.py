from app.models import PointsLedger, RecipeFavourite, SearchTerm

def test_phase2_phase3_models_registered(app):
    from app.models import db
    assert "points_ledger" in db.metadata.tables
    assert "recipe_favourites" in db.metadata.tables
    assert "search_terms" in db.metadata.tables

def test_share_script_exists():
    from pathlib import Path
    assert Path("app/static/js/share.js").exists()
    assert Path("app/static/js/recipe-cook.js").exists()
