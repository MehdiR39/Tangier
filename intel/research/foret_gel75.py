"""Le gel de la foret a 75 s : meme regle, meme critere que foret_gel, decision avec toute la premiere
minute de transactions et entree au dernier prix <= 77 s. Module a part pour que le gardien le voie
sous son propre nom. Voir foret_gel.py, en-tete."""
import os
os.environ["AGE_DECISION"] = "75"
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from foret_gel import main  # noqa: E402

if __name__ == "__main__":
    main()
