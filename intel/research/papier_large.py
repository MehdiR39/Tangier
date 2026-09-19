"""Instance papier_large de papier_gd_direct (PAPIER_GD_REGLE=large, PAPIER_GD_DB=/app/db/papier_large.sqlite). Module a part pour que le gardien la voie sous son propre nom
et la relance si elle tombe : les trois instances sont mortes le 18/09 a 9h14 sans que personne ne le voie
(§3.149). Ne fait rien d autre que fixer l environnement et appeler papier_gd_direct.main()."""
import os
os.environ.setdefault("PAPIER_GD_REGLE", "large")
os.environ.setdefault("PAPIER_GD_DB", "/app/db/papier_large.sqlite")
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from papier_gd_direct import main  # noqa: E402

if __name__ == "__main__":
    main()
