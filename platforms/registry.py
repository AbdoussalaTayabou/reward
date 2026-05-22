"""
Registre extensible des plateformes partenaires (offerwalls, régies pub, etc.).

Pour ajouter une nouvelle plateforme :
  1. Ajouter une entrée dans PLATFORMS ci-dessous.
  2. (Optionnel) Définir la fonction de signature du postback dans verify_postback().
  3. Ajouter les variables d'env / secrets correspondants (clé API, secret de postback).

Champs :
  slug          : identifiant interne (URL safe), unique
  name          : nom affiché
  category      : 'survey' | 'video' | 'task' | 'offerwall' | 'ads' | 'cashback'
  description   : texte court (FR)
  logo          : URL ou chemin static (placeholder par défaut)
  color         : classe Tailwind pour la pastille
  enabled       : visible sur le hub
  internal      : True = utilise nos propres routes (surveys/videos/tasks)
                  False = plateforme externe (redirection + postback)
  redirect_url  : URL de base (peut contenir {user_id}, {sub_id})
  postback_secret_env : nom de la variable d'env contenant le secret
  min_payout    : indication UX (points)
"""

PLATFORMS = [
    # --- Modules internes (existants) -------------------------------------
    {
        "slug": "surveys",
        "name": "Sondages",
        "category": "survey",
        "description": "Réponds à des questionnaires courts et gagne des points.",
        "color": "from-indigo-500 to-indigo-700",
        "icon": "📝",
        "enabled": True,
        "internal": True,
        "endpoint": "surveys.list_surveys",   # url_for()
    },
    {
        "slug": "videos",
        "name": "Vidéos",
        "category": "video",
        "description": "Regarde des vidéos sponsorisées pour cumuler des points.",
        "color": "from-rose-500 to-rose-700",
        "icon": "🎬",
        "enabled": True,
        "internal": True,
        "endpoint": "videos.list_videos",
    },
    {
        "slug": "tasks",
        "name": "Tâches",
        "category": "task",
        "description": "Micro-tâches manuelles validées par notre équipe.",
        "color": "from-emerald-500 to-emerald-700",
        "icon": "✅",
        "enabled": True,
        "internal": True,
        "endpoint": "tasks.list_tasks",
    },

    # --- Plateformes externes (offerwalls / régies) -----------------------
    # Activer dès que les clés sont configurées côté admin.
    {
        "slug": "cpx-research",
        "name": "CPX Research",
        "category": "offerwall",
        "description": "Des centaines de sondages internationaux à forte rémunération.",
        "color": "from-blue-500 to-blue-700",
        "icon": "🌍",
        "enabled": False,
        "internal": False,
        "redirect_url": "https://offers.cpx-research.com/index.php?app_id={app_id}&ext_user_id={user_id}",
        "postback_secret_env": "CPX_RESEARCH_SECRET",
        "config_env": {"app_id": "CPX_RESEARCH_APP_ID"},
        "min_payout": 50,
    },
    {
        "slug": "adgate",
        "name": "AdGate Media",
        "category": "offerwall",
        "description": "Offres mobiles, installations d'apps et essais gratuits.",
        "color": "from-fuchsia-500 to-fuchsia-700",
        "icon": "📱",
        "enabled": False,
        "internal": False,
        "redirect_url": "https://wall.adgaterewards.com/{wall_code}/{user_id}",
        "postback_secret_env": "ADGATE_SECRET",
        "config_env": {"wall_code": "ADGATE_WALL_CODE"},
        "min_payout": 100,
    },
    {
        "slug": "offertoro",
        "name": "OfferToro",
        "category": "offerwall",
        "description": "Mur d'offres global avec validations rapides.",
        "color": "from-amber-500 to-amber-700",
        "icon": "🎯",
        "enabled": False,
        "internal": False,
        "redirect_url": "https://www.offertoro.com/ifr/show/{pub_id}/{user_id}/{app_id}",
        "postback_secret_env": "OFFERTORO_SECRET",
        "config_env": {"pub_id": "OFFERTORO_PUB_ID", "app_id": "OFFERTORO_APP_ID"},
        "min_payout": 80,
    },
    {
        "slug": "google-ads",
        "name": "Google Ads",
        "category": "ads",
        "description": "Récompenses sur clics et conversions Google Ads (via postback).",
        "color": "from-sky-500 to-sky-700",
        "icon": "🟦",
        "enabled": False,
        "internal": False,
        "redirect_url": "{google_redirect}?sub_id={user_id}",
        "postback_secret_env": "GOOGLE_ADS_SECRET",
        "config_env": {"google_redirect": "GOOGLE_ADS_REDIRECT"},
        "min_payout": 200,
    },
    {
        "slug": "meta-ads",
        "name": "Meta Ads",
        "category": "ads",
        "description": "Engagement publicitaire Facebook / Instagram récompensé.",
        "color": "from-blue-600 to-indigo-700",
        "icon": "🅵",
        "enabled": False,
        "internal": False,
        "redirect_url": "{meta_redirect}?sub_id={user_id}",
        "postback_secret_env": "META_ADS_SECRET",
        "config_env": {"meta_redirect": "META_ADS_REDIRECT"},
        "min_payout": 200,
    },
    {
        "slug": "tiktok-ads",
        "name": "TikTok Ads",
        "category": "ads",
        "description": "Découvre des marques et gagne via les campagnes TikTok.",
        "color": "from-slate-800 to-slate-900",
        "icon": "🎵",
        "enabled": False,
        "internal": False,
        "redirect_url": "{tiktok_redirect}?sub_id={user_id}",
        "postback_secret_env": "TIKTOK_ADS_SECRET",
        "config_env": {"tiktok_redirect": "TIKTOK_ADS_REDIRECT"},
        "min_payout": 200,
    },
]


def all_platforms(include_disabled: bool = False):
    return [p for p in PLATFORMS if include_disabled or p["enabled"]]


def by_slug(slug: str):
    for p in PLATFORMS:
        if p["slug"] == slug:
            return p
    return None


def by_category():
    cats = {}
    for p in all_platforms():
        cats.setdefault(p["category"], []).append(p)
    return cats
