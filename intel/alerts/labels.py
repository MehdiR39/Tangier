"""Human-readable (French) labels for states, actions, alert kinds and severities."""
from __future__ import annotations

STATE_FR = {
    "DISCOVER": "Découverte",
    "EARLY_ACCUMULATION": "Accumulation précoce",
    "ACCUMULATION": "Accumulation en cours",
    "BREAKOUT": "Ça décolle",
    "BREAKOUT_CONFIRMED": "Décollage confirmé",
    "WATCH": "À surveiller",
    "EXTENDED": "Déjà trop monté",
    "DISTRIBUTION": "Les gros porteurs vendent",
    "THESIS_BREAK": "Thèse cassée",
    "SECURITY_RISK": "Risque sur le contrat",
    "REJECTED": "Éliminé",
}

ACTION_FR = {
    "HOLD": "GARDER",
    "WATCH": "SURVEILLER",
    "DO_NOT_ADD": "NE PAS RENFORCER",
    "REVIEW_EXIT": "ENVISAGER LA SORTIE",
    "CANDIDATE": "CANDIDAT SÉRIEUX",
    "REJECT": "ÉLIMINÉ",
}

KIND_FR = {
    "state_change": None,  # title comes from the state
    "lp_drop": "La liquidité part",
    "top_wallet_distribution": "Les gros wallets allègent",
    "whale_accumulation": "Les baleines achètent",
    "whale_distribution": "Les baleines vendent",
    "holder_acceleration": "Afflux de nouveaux holders",
    "divergence": "Divergence prix / holders",
    "score_change": "Score en forte variation",
    "hard_filters_pass": "A passé tous les filtres",
    "moonshot_candidate": "Candidat sérieux",
}

SEVERITY_FR = {
    "CRITICAL": "🚨 Critique",
    "IMPORTANT": "⚠️ Important",
    "WATCH": "👀 À surveiller",
    "INFO": "ℹ️ Info",
}

# One sentence telling a non-technical reader what to do with the message.
MEANING_FR = {
    "DISTRIBUTION": "Signal de prudence : ceux qui détiennent le plus vendent. Pas de panique, mais n'achète pas maintenant et surveille la liquidité.",
    "THESIS_BREAK": "Ce qui justifiait la position n'est plus là (liquidité partie, holders en fuite ou chute profonde). Réfléchis à sortir.",
    "SECURITY_RISK": "Le contrat présente un blocage ou un pouvoir dangereux. Ne pas toucher tant que ce n'est pas levé.",
    "EXTENDED": "Le token a déjà fait l'essentiel de sa hausse sans que les holders suivent : acheter ici, c'est acheter le sommet.",
    "BREAKOUT": "Hausse rapide avec de vrais acheteurs et des holders qui augmentent. Intéressant, mais attends la confirmation.",
    "BREAKOUT_CONFIRMED": "La hausse tient depuis plusieurs heures avec des holders qui continuent d'arriver.",
    "ACCUMULATION": "Le nombre de porteurs monte sans que le prix s'emballe : profil sain, à suivre.",
    "EARLY_ACCUMULATION": "Token jeune avec des porteurs qui arrivent et un prix encore proche du premier vrai marché.",
    "WATCH": "Rien de directionnel pour l'instant.",
    "REJECTED": "Éliminé par les filtres (liquidité, concentration ou sécurité).",
    "DISCOVER": "Trop tôt pour juger : données encore incomplètes.",
    "lp_drop": "Quelqu'un retire de l'argent du pool. Ça n'annonce pas forcément une baisse, mais ça rend la sortie plus difficile.",
    "top_wallet_distribution": "Plusieurs gros porteurs réduisent leur position. Souvent le début d'une phase de distribution.",
    "whale_accumulation": "De gros wallets achètent sans que la concentration augmente : plutôt bon signe, à confirmer.",
    "whale_distribution": "Les gros wallets vendent nettement plus qu'ils n'achètent.",
    "holder_acceleration": "Le nombre de nouveaux porteurs accélère. Bon signe si le prix ne s'est pas déjà envolé.",
    "divergence": "Le prix et les holders ne racontent pas la même histoire : à regarder de près.",
    "score_change": "Le score global a bougé nettement depuis la dernière fois.",
    "hard_filters_pass": "Le token n'a aucun défaut rédhibitoire ; ce n'est pas encore un signal d'achat.",
    "moonshot_candidate": "Toutes les conditions d'un candidat sérieux sont réunies. À étudier avant d'agir.",
}


def state_fr(state: str | None) -> str:
    return STATE_FR.get(state or "", state or "?")


def action_fr(action: str | None) -> str:
    return ACTION_FR.get(action or "", action or "?")


def kind_title_fr(kind: str, state: str | None) -> str:
    t = KIND_FR.get(kind)
    return t if t else state_fr(state)


def meaning_fr(kind: str, state: str | None) -> str:
    if kind == "state_change":
        return MEANING_FR.get(state or "", "")
    return MEANING_FR.get(kind, "")
