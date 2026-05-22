# Étape 9bis — Hub "Gagner" + plateformes extensibles

Ce patch **réintègre les boutons Sondages / Vidéos / Tâches** dans la nouvelle
interface pro **et** prépare l'ajout futur de plateformes externes
(CPX Research, AdGate, OfferToro, Google Ads, Meta Ads, TikTok Ads, …) via un
simple registre Python.

## Fichiers livrés

```
platforms/__init__.py
platforms/registry.py                       ← liste centralisée des plateformes
platforms/routes.py                         ← /earn, /earn/go/<slug>, /earn/postback/<slug>
templates/base.html                         ← MAJ : mega-menu "Gagner" + version mobile
templates/earn/hub.html                     ← page hub /earn
templates/partials/earn_menu.html           ← (optionnel) menu réutilisable
templates/partials/dashboard_quick_actions.html  ← à inclure dans le dashboard
PATCH_app.py.txt                            ← snippet à coller dans create_app()
```

## Intégration (3 étapes)

1. **Copier** le dossier `platforms/` et les templates à la racine du projet
   (en remplaçant `templates/base.html`).
2. **Coller** dans `app.py / create_app()` (voir `PATCH_app.py.txt`) :

   ```python
   from platforms.routes import platforms_bp
   from platforms.registry import all_platforms
   app.register_blueprint(platforms_bp)

   @app.context_processor
   def inject_platforms():
       return {"nav_platforms": all_platforms()}
   ```

3. **(Optionnel)** Inclure dans `templates/dashboard/home.html` :

   ```jinja
   {% include 'partials/dashboard_quick_actions.html' %}
   ```

## Ajouter une nouvelle plateforme

Ouvrir `platforms/registry.py`, ajouter une entrée :

```python
{
  "slug": "ma-plateforme",
  "name": "Ma Plateforme",
  "category": "offerwall",            # survey | video | task | offerwall | ads | cashback
  "description": "Texte court.",
  "color": "from-pink-500 to-pink-700",
  "icon": "💎",
  "enabled": True,
  "internal": False,
  "redirect_url": "https://partner.com/?uid={user_id}&key={api_key}",
  "postback_secret_env": "MAPLATEFORME_SECRET",
  "config_env": {"api_key": "MAPLATEFORME_KEY"},
  "min_payout": 100,
},
```

Configurer les variables d'environnement correspondantes, c'est tout :
le menu "Gagner", le hub `/earn` et le postback `/earn/postback/ma-plateforme`
sont disponibles automatiquement.

## Postback S2S (commun à toutes les plateformes externes)

```
GET /earn/postback/<slug>?user_id=<id>&amount=<pts>&tx_id=<unique>&sig=<hmac_sha256>
```

`sig = HMAC_SHA256(secret, f"{user_id}|{amount}|{tx_id}")`

Le crédit utilise `credit_points()` (helper de l'étape 1) avec `external_id=tx_id`
pour rester idempotent.
