# Meet My Mama – Détection d'opportunités traiteur (BOAMP, Île-de-France)

Prototype du cas pratique « AI GTM Engineer » : repérer les organisations franciliennes qui auront besoin d'un traiteur dans les prochaines semaines, à partir des avis de marchés publics du BOAMP.

**Le rapport complet du cas (5 parties) est dans [`REPORT.pdf`](REPORT.pdf) / [`REPORT.md`](REPORT.md).**

## Lancer

```bash
pip install -r requirements.txt
python boamp_opportunities.py                  # fenêtre de 180 jours de parution (défaut)
python boamp_opportunities.py --since-days 240 # pour élargir
python expected_value.py                       # valeur attendue du top 5 (hypothèses en tête de fichier)
```

Aucune clé API n'est nécessaire : l'API du BOAMP est publique. L'option `--llm` (contrôle par un LLM) demande en plus `pip install anthropic` et la variable `ANTHROPIC_API_KEY`.

## Ce que fait le script

1. **Extraction** : 14 requêtes plein texte sur l'API publique du BOAMP (traiteur, cocktail, buffet, plateaux repas, banquet, cérémonie…).
2. **Nettoyage et contrôle qualité**
   - Dédoublonnage.
   - Île-de-France : la majorité des départements de l'avis doit être francilienne, car « 75 » figure dans beaucoup d'avis nationaux.
   - Avis expirés écartés.
   - Rectificatifs fusionnés ; un rectificatif sans date hérite de la date de son avis d'origine.
   - Attributions mises de côté.

   Chaque rejet est tracé dans `rejets_boamp.csv`.
3. **Scoring**
   - *Score de conversion (0-100)* : il combine trois facteurs.
     - L'adéquation métier : mots-clés dans l'**objet** de l'avis et codes CPV traiteur. Le texte intégral ne compte qu'en appoint, et jamais pour les mots ambigus comme « réception ».
     - L'avantage « traiteur engagé » : marché réservé, clauses sociales, insertion.
     - L'accessibilité pour une petite structure : procédure adaptée, montant, type d'acheteur.

     Un avis sans besoin traiteur explicite (objet ou CPV) est rejeté. Ce score est relatif : ce n'est **pas** une probabilité calibrée.
   - *Score d'urgence (0-100)* : il est maximal entre 3 et 21 jours avant la date limite. Au-delà de 180 jours, il s'agit probablement d'une candidature permanente (système d'acquisition dynamique).
   - *Priorité* = conversion × (0,5 + 0,5 × urgence/100). La formule est multiplicative : l'urgence ne peut pas faire remonter un avis hors cible.
4. **Acheteurs récurrents** : ce sont les acheteurs franciliens qui ont acheté du traiteur ces derniers mois. Depuis le 01/04/2026, un acheteur public peut commander sans mise en concurrence sous 60 000 € HT : ce sont donc des cibles de prospection directe.
5. **Option IA (`--llm`)** : un LLM extrait le type de besoin, le nombre de convives et la date de l'événement. Le script vérifie que la citation justificative existe mot pour mot dans l'avis, et que le nombre de convives apparaît bien dans le texte.

## Sorties (`output/`)

| Fichier | Contenu |
|---|---|
| `opportunites_boamp.csv` | Opportunités classées, avec un `statut` (ouvert / à vérifier) et une colonne `verif_manuelle` |
| `acheteurs_recurrents.csv` | Acheteurs ayant déjà acheté du traiteur : cibles de prospection directe |
| `attributions_boamp.csv` | Marchés attribués : signal de renouvellement ou de sous-traitance |
| `rejets_boamp.csv` | Avis écartés et raison, pour auditer les filtres |
| `qa_report.txt` | Compteurs de chaque étape de contrôle |
| `top5_valeur_attendue.csv` | Résultat de `expected_value.py` |

## Itérations : ce que les données réelles ont corrigé

**v1 → v2.** Le premier run a sorti 297 « opportunités », dont environ 270 faux positifs :
- « réception » matchait « accusé de réception » ou « réception des travaux » ;
- des avis de province passaient à cause d'un « 75 » dans leur liste de départements ;
- la priorité additive faisait remonter des avis urgents mais hors sujet ;
- l'exclusion « assurance » éliminait la Caisse primaire d'**assurance** maladie de Paris, qui cherche pourtant un traiteur.

**v2 → v3.** Le run v2 (22 opportunités, relues une à une) a révélé trois défauts :
- un rectificatif sans date restait « ouvert » alors que l'avis d'origine avait expiré ;
- « Chambres d'agri*culture* » était classé « Culture » ;
- la requête « réception » plafonnait à 9 900 résultats sans rien apporter.

La v3 corrige ces trois points et ajoute la liste des acheteurs récurrents.
