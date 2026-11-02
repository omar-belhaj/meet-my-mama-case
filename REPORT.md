# Meet My Mama : aller chercher le business avant qu'il ne se voie

**Cas pratique, stage AI GTM Engineer.** Omar. Données extraites le 27 octobre 2026.

**Résumé**
- **Source retenue : les marchés publics (BOAMP).** C'est la seule source publique où une organisation écrit noir sur blanc « j'ai besoin d'un traiteur », avec une date limite et un budget.
- **Prototype :** un script Python, reproductible et sans clé API. Sur 17 131 avis bruts, il a extrait **22 consultations traiteur ouvertes en Île-de-France**.
- **Vérification :** j'ai relu chaque ligne. **16 sont confirmées, 4 sont à vérifier et 2 sont des faux positifs.**
- **Un sous-produit utile :** **une quarantaine d'acheteurs publics** qui ont acheté du traiteur ces six derniers mois et qu'on peut prospecter en direct.
- **Valeur :** mon top 5 représente **environ 64 k€ HT de valeur attendue**, avec des hypothèses prudentes et explicites. Deux dossiers se jouent avant le 6 novembre.

---

## 1. Signaux d'achat : où voir le besoin avant les concurrents

J'ai cherché des signaux qui disent **qui** aura besoin d'un traiteur et **quand**. Un bon signal est daté, public, et automatisable.

| # | Source publique | Ce que le signal dit | Délai avant le besoin | Fiabilité du signal | Accès |
|---|---|---|---|---|---|
| 1 | **Appels d'offres** (BOAMP, profils acheteurs comme PLACE ou Maximilien) | Besoin **explicite** : objet, budget, date limite, parfois date de l'événement | 1 à 10 semaines | **Très élevée** : le besoin est écrit | API ouverte, gratuite |
| 2 | **Historique des marchés** (avis d'attribution BOAMP, données essentielles de la commande publique sur data.gouv) | Qui achète du traiteur, combien, et quand le contrat expire | Renouvellement à 1-4 ans ; achat direct possible dès maintenant | Élevée sur le besoin, moyenne sur le timing | API ouverte |
| 3 | **Offres d'emploi** « office manager », « chargé·e d'événements », « happiness manager » (API France Travail, job boards) | L'entreprise structure sa vie interne et ses événements | 1 à 3 mois | Moyenne : signal indirect, la personne recrutée sera l'acheteuse | API France Travail (clé gratuite) |
| 4 | **Déménagements et nouveaux établissements** (BODACC, API Recherche d'entreprises) | Transfert de siège ou ouverture d'un site : inauguration, crémaillère | 1 à 3 mois | Faible à moyenne : beaucoup de domiciliations sans locaux réels ; à filtrer par effectif | API ouverte |
| 5 | **Levées de fonds** (presse startup, communiqués) | Croissance, recrutements, séminaires, team building | 1 à 6 mois | Moyenne : le besoin est probable mais pas daté | Scraping ou flux RSS |
| 6 | **Calendrier et engagements RSE** (vœux en janvier, Mois de l'ESS en novembre, semaine du handicap, 8 mars ; entreprises engagées sur la diversité) | Besoin saisonnier et affinité forte avec la mission de Meet My Mama | Connu à l'avance | Élevée sur la date, faible sur le choix du traiteur | Calendrier et rapports RSE |

Deux points d'ingénieur sur ces sources :
- **Les signaux se combinent.** Une entreprise qui déménage (4), qui recrute un office manager (3) et qui a levé des fonds (5) est un lead bien plus chaud que chaque signal pris seul. C'est exactement ce que fait un outil comme Clay.
- **Méfiance envers les agendas d'événements publics.** Les salons et grands lieux parisiens fonctionnent souvent avec des **traiteurs référencés ou exclusifs**. L'événement est visible, mais le marché y est fermé. Je ne l'ai donc pas retenu comme source prioritaire.

**Pourquoi le BOAMP pour le prototype ?** C'est la seule source où l'on ne devine pas le besoin : on le lit. Elle répond aussi exactement à la question posée (« dans les prochaines semaines »), puisque chaque avis a une date limite. Et elle vise un segment que Meet My Mama ne travaille sans doute pas encore : l'achat public, où les **clauses sociales** et les **marchés réservés** peuvent transformer la mission sociale en critère de notation.

---

## 2. Prototype : `boamp_opportunities.py`

### Ce qu'il fait

```
API BOAMP (15 requêtes) → 20 556 avis → dédoublonnage (17 131) → filtres → scoring → 22 opportunités
                                                  │
                                    rejets tracés + rapport qualité
```

1. **Extraction.** Le script envoie 14 recherches plein texte (15 en v2, avant la suppression de « réception ») à l'API publique du BOAMP : traiteur, cocktail, buffet, plateaux repas, banquet, cérémonie, etc. La fenêtre couvre les avis publiés depuis 180 jours.
2. **Filtres.** Ils sont appliqués dans cet ordre :
   - Île-de-France : la majorité des départements de l'avis doit être francilienne ;
   - avis encore ouverts uniquement ;
   - rectificatifs fusionnés avec l'avis d'origine ;
   - attributions mises de côté, car elles servent un autre usage (voir plus bas).
3. **Scoring.** Le détail est dans le tableau ci-dessous.
4. **Sorties.**
   - `opportunites_boamp.csv` : les opportunités classées, avec une colonne de vérification manuelle ;
   - `rejets_boamp.csv` : chaque avis écarté avec sa raison, pour qu'un humain puisse auditer le filtre ;
   - `acheteurs_recurrents.csv` ;
   - `qa_report.txt`.

### Logique de scoring

Le script calcule deux scores, puis les combine en une priorité.

| Score | Composantes | Pourquoi |
|---|---|---|
| **Conversion** (0-100) | • Adéquation métier (70 %) : mots-clés dans l'**objet** de l'avis et codes CPV traiteur (55520000…).<br>• Avantage « traiteur engagé » (30 %) : marché réservé, clause sociale, insertion.<br>• Multiplicateur d'accessibilité : procédure adaptée, montant raisonnable, type d'acheteur. | On gagne quand le besoin correspond au cœur de métier et que la grille de notation valorise ce qui différencie Meet My Mama. |
| **Urgence** (0-100) | Maximale entre 3 et 21 jours avant la date limite. Basse sous 3 jours, car une offre bâclée est perdue d'avance. | Ce qui compte, c'est le temps d'agir utilement, pas seulement la proximité de la date. |
| **Priorité** | Conversion × (0,5 + 0,5 × urgence/100) | La formule est **multiplicative** : l'urgence ne peut pas faire remonter un avis hors sujet. Je l'ai appris à mes dépens (voir ci-dessous). |

Une limite importante : ce score de conversion **n'est pas une probabilité calibrée**. C'est un ordre de priorité fondé sur des règles. Il deviendra une probabilité quand on aura un historique (partie 3).

### Comment j'ai vérifié la qualité (et ce qui a cassé)

**Premier run : 297 « opportunités », dont environ 270 fausses.** En lisant les résultats, j'ai trouvé quatre défauts :
- **« Réception » était un mot-clé piège.** Il correspond le plus souvent à « accusé de réception » ou « réception des travaux ». Résultat : des marchés d'assurance, de photocopieurs ou de maîtrise d'œuvre classés comme opportunités traiteur. En plus, cette requête saturait l'API (9 900 résultats, la limite) : elle coûtait du temps et du rappel pour rien.
- **Le code département « 75 » est présent dans la liste de nombreux avis nationaux.** La CPAM du Maine-et-Loire, le CH d'Arras ou le canal Seine-Nord passaient donc pour franciliens.
- **La formule de priorité additive** faisait remonter des avis urgents mais hors sujet.
- **Ma règle d'exclusion « assurance »** éliminait la **CPAM de Paris**, qui lance pourtant un marché traiteur de 1,2 M€. Je l'ai repéré en relisant les rejets.

**Correctifs de la v2.**
- Un besoin traiteur doit être **explicite**, soit dans l'objet de l'avis, soit dans un code CPV traiteur.
- Les mots ambigus ne comptent plus dans le texte intégral.
- Un avis est francilien seulement si la majorité de ses départements le sont.
- La priorité devient multiplicative.

**Contrôle humain sur les 22 lignes du run v2** (relecture de l'objet, de l'acheteur, des dates et des codes CPV de chaque avis ; ouverture des avis du top 5 sur boamp.fr).
- **16 consultations traiteur réelles, ouvertes et franciliennes.**
- **2 faux positifs :**
  - Vincennes achète du *matériel* de cérémonie, pas un traiteur.
  - Le SISVM relève de la restauration collective (repas et goûters).
- **4 à vérifier :**
  - **Les rectificatifs sans date limite de Paris-Saclay et de l'OFB.** Pour Paris-Saclay, l'avis d'origine a expiré le 5 octobre : le script gardait un « fantôme ». C'est corrigé en v3 par une règle : un rectificatif hérite de la date de son avis d'origine.
  - **Eau de Paris et l'Académie des Beaux-Arts**, en procédure négociée ou restreinte : la phase de candidature est peut-être déjà close.
- **Cas limites, conservés mais déclassés :** la sonorisation événementielle de Plaine Commune (partenaire potentiel, pas client) et la concession du restaurant de Chaillot (ce n'est pas du traiteur).

**Ce que je n'ai pas pu vérifier automatiquement.**
- **Le montant estimé.** Il est extrait par heuristique du JSON de l'avis, dont la structure varie d'un avis à l'autre. Il n'est trouvé que pour 9 avis sur 22. Je prends la plus grande valeur : elle peut correspondre au montant maximum sur 4 ans, ou au montant d'un seul lot.
- **Les champs exacts de l'API.** Le code les lit de façon défensive et trace les avis sans département ni date limite.

### Sous-produit : les acheteurs récurrents

Le script repère aussi **environ 40 acheteurs franciliens qui ont acheté du traiteur ces six derniers mois**. Il les trouve dans deux types d'avis : les consultations closes et les attributions. Exemples : ENS Paris-Saclay, Gennevilliers, Rueil-Malmaison, les CCAS de Massy, Sèvres et Montreuil, l'École polytechnique, la Présidence de la République.

Ces acheteurs ouvrent trois leviers :
1. **Le renouvellement.** La date de fin du marché est connue : on peut préparer la prochaine consultation des mois à l'avance.
2. **La sous-traitance.** Le lauréat d'un gros accord-cadre peut avoir besoin d'un partenaire pour certains formats, par exemple une cuisine du monde ou un événement RSE.
3. **L'achat direct.** Depuis le 1er avril 2026, un acheteur public peut commander **sans publicité ni mise en concurrence jusqu'à 60 000 € HT** ([décret 2025-1386](https://blog.landot-avocats.net/2026/04/01/marches-publics-relevement-du-seuil-de-dispense-de-procedure-a-60-000-e-des-aujourdhui/)). Cela concerne les besoins qui ne sont pas déjà couverts par un accord-cadre. Un CCAS qui organise un événement ponctuel peut donc choisir Meet My Mama directement.

---

## 3. Vision data : prédire quelles opportunités deviennent des commandes

**Cible.** Pour chaque opportunité (lead, demande de devis ou appel d'offres), `y = 1` si elle aboutit à une commande dans les 90 jours. Pour estimer le chiffre d'affaires, j'ajouterais un second modèle : le montant si commande. Valeur attendue = P(commande) × montant.

**Variables.** Il faut les figer **au moment du devis**, sinon on fuit de l'information du futur.
- **Opportunité :** canal ou signal d'origine (AO, entreprise, agence, entrant), délai entre la demande et l'événement, nombre de convives, budget par personne, format (cocktail, buffet, plateaux), mois de l'événement.
- **Client :** type (entreprise, public, agence), taille, déjà client ou non, nombre de commandes passées, ancienneté, présence d'engagements RSE.
- **Processus :** délai de réponse au devis, nombre de relances, dégustation proposée ou non, écart avec le prix habituel.
- **Pour les AO :** procédure, critères de notation (part prix ou part sociale), nombre de lots, montant.

**Modèle.** Je commencerais par une **régression logistique régularisée**. Avec peu de données, elle est stable et interprétable : le DG peut lire pourquoi un lead est chaud. Quand on dépassera quelques centaines d'opportunités, je passerais à du **gradient boosting** (LightGBM, ou CatBoost qui gère bien les variables catégorielles), avec SHAP pour garder l'explicabilité.

**Évaluation.**
- Un découpage **temporel** : entraînement sur le passé, test sur les mois suivants. Un découpage aléatoire mélangerait les saisons.
- **PR-AUC**, car les commandes sont minoritaires.
- **Calibration**, car on multiplie la probabilité par un montant, donc elle doit être juste.
- Et la métrique business : le **taux de conversion du top 20 % des leads** comparé au taux moyen.

**Avec peu de données au départ.**
1. **Partir des règles du prototype.** On les utilise comme a priori, puis on recalibre leurs poids dès qu'il y a 50 à 100 résultats (régression logistique sur les scores existants).
2. **Utiliser un modèle bayésien hiérarchique** : un taux de conversion par canal et par segment, « tiré » vers la moyenne globale tant qu'il y a peu d'observations.
3. **Instrumenter tout de suite** l'ERP Inside et le CRM Attio, pour enregistrer chaque opportunité *perdue* avec sa raison (prix, date, capacité, pas de réponse). Sans les échecs, aucun modèle n'est possible.
4. **Réentraîner chaque mois** et comparer le modèle aux décisions de l'équipe commerciale avant de lui confier la priorisation.

---

## 4. Passage à l'action : top 5 et plan de la semaine

### Le top 5

Je n'ai pas pris mécaniquement les 5 premiers du score. Trois raisons :
- **Crégy-lès-Meaux** est bien notée, mais elle est en Seine-et-Marne, loin de Nanterre. La logistique (livraison, personnel) coûte cher.
- **Eau de Paris et l'Académie des Beaux-Arts** doivent d'abord être vérifiées.
- **La CPAM de Paris** (1,2 M€, date limite le 30 novembre) est un « stretch » : à regarder en co-traitance ou sur un seul lot.

| Acheteur | Date limite | Montant HT | Taux de consommation | Valeur captable | ≈ Nb de prestations | P(gain) | **Valeur attendue** |
|---|---|---|---|---|---|---|---|
| Ville d'Élancourt (78), vœux du Maire | **6 nov.** | 90 k€ | 60 % | 54 k€ | 22 | 20 % | **10,8 k€** |
| Romainville (93), traiteurs et boulangeries artisanales | **6 nov.** | 50 k€ | 60 % | 30 k€ | 12 | 20 % | **6,0 k€** |
| CCAS de Chevilly-Larue (94), banquet des aînés | 9 nov. | 160 k€ | 80 % | 128 k€ | 51 | 15 % | **19,2 k€** |
| CCAS de Créteil (94), banquet seniors de janvier 2027 | 16 nov. | ~20 k€ *(non publié)* | 100 % | 20 k€ | 8 | 20 % | **4,0 k€** |
| Villeneuve-la-Garenne (92), manifestations municipales | 30 nov. | 340 k€ | 60 % | 204 k€ | 82 | 12 % | **24,5 k€** |
| **Total** | | | | | | | **≈ 64 k€** |

**Hypothèses** (paramétrables dans `expected_value.py`) :
- **Panier moyen : 2 500 € HT par prestation**, soit environ 80 convives à 30 € HT.
- **Taux de consommation : 60 %.** Un accord-cadre publie un montant *maximum*, et on en consomme rarement la totalité. J'ai pris 80 % pour un banquet aux volumes plus fermes.
- **P(gain) de 12 à 20 %** : environ 1 chance sur 5 à 8 soumissionnaires, réduite pour les gros volumes plus disputés.
- **Le montant de Créteil est une hypothèse** (500 convives × 40 € HT).

Le portefeuille vaut **32 k€ si ces taux de gain sont deux fois trop optimistes, et 129 k€ s'ils sont deux fois trop prudents.** Le vrai chiffre clé, c'est le taux de gain historique de Meet My Mama en appels d'offres : c'est la première question que je poserais.

### Comment je les contacterais cette semaine

Une précision importante d'abord : **pendant une consultation publique, on ne « prospecte » pas l'acheteur.** Les échanges passent par la plateforme de l'acheteur, et un contact parallèle peut fragiliser l'offre. Le « message commercial », c'est l'offre elle-même. Le plan :

- **Lundi : décider vite.**
  - Télécharger les dossiers de consultation des 5 marchés et lire les critères de notation.
  - Décider go ou no-go avec le DG en 30 minutes par dossier, sur trois questions : capacité de production, critères sociaux et environnementaux, prix plancher.
- **Lundi et mardi : poser les questions.**
  - Envoyer les questions via les plateformes (exemple ci-dessous). La date limite des questions tombe souvent 6 à 10 jours avant celle des offres : pour Élancourt et Romainville, c'est maintenant.
- **Mardi à jeudi : écrire les deux offres du 6 novembre** (Élancourt et Romainville).
  - Un mémoire technique réutilisable : les Mamas, la Mama Academy, l'approvisionnement, la logistique, des photos de prestations.
  - Des attestations prêtes une fois pour toutes (DUME, Kbis, assurances, attestations URSSAF et fiscales).
  - Vérifier avec la direction le statut ESS ou ESUS de Meet My Mama : il pourrait ouvrir certains marchés réservés.
- **Vendredi : préparer la suite.**
  - Lancer les dossiers de Chevilly-Larue et Créteil.
  - En parallèle, écrire **directement** aux 10 meilleurs acheteurs récurrents qui n'ont pas d'accord-cadre en cours (levier des 60 000 € HT).

### Message : question à la Ville d'Élancourt, via sa plateforme

> **Objet : Consultation « Prestations de traiteur – cérémonies des vœux du Maire » – questions**
>
> Madame, Monsieur,
>
> Dans le cadre de la préparation de notre offre, pourriez-vous nous préciser :
>
> 1. le nombre de convives attendus par cérémonie, et la répartition entre la cérémonie aux personnalités et celle à la population, si elles sont distinctes ;
> 2. les dates et le lieu prévisionnels de l'édition 2027, ainsi que les équipements disponibles sur place (office, points d'eau, électricité) ;
> 3. si une dégustation est prévue dans l'analyse des offres, et si des variantes de menu sont admises (formats végétariens, cuisines du monde, produits de saison) ;
> 4. si l'acheteur valorise, dans le critère de valeur technique, les engagements sociaux du prestataire (insertion professionnelle, formation) et la réduction du gaspillage.
>
> Pour information, Meet My Mama est un traiteur engagé basé à Nanterre. Nos cheffes, les Mamas, sont des femmes venues du monde entier que nous formons et accompagnons vers l'entrepreneuriat culinaire.
>
> Nous vous remercions par avance.
>
> Bien cordialement,
> [Prénom Nom], Meet My Mama

Chaque question sert l'offre : la jauge sert au chiffrage, le lieu à la logistique. La question 4 fait exister le positionnement de Meet My Mama auprès de l'acheteur sans sortir du cadre réglementaire.

---

## 5. Regard critique sur l'IA

- **Où elle m'a fait gagner du temps.**
  - Le squelette du script, la gestion de l'API et du parcours du JSON hétérogène du BOAMP, les listes de mots-clés et de codes CPV, et la mise en forme des sorties.
  - Ce sont des heures de code sans enjeu, faites en quelques minutes.
  - Elle a aussi structuré le recensement des signaux d'achat et rappelé le relèvement du seuil à 60 000 €, que j'ai ensuite vérifié à la source.
- **Où elle m'a induit en erreur.** Les erreurs de la v1 venaient toutes de règles proposées par l'IA, plausibles sur le papier :
  - « réception » comme mot-clé ;
  - l'exclusion « assurance », qui écartait la CPAM ;
  - le filtre « au moins un département francilien » ;
  - un classement d'acheteurs où « agri*culture* » devenait « Culture ».

  Elle a aussi supposé les noms des champs de l'API sans pouvoir les vérifier. Aucune de ces erreurs ne faisait planter le code : il produisait 297 lignes propres et fausses. **C'est la lecture des rejets et des résultats par un humain qui les a révélées.** Enfin, l'IA invente facilement un « nombre de convives » ou une date d'événement absents de l'avis. C'est pourquoi l'option `--llm` du script exige une citation mot pour mot et vérifie qu'elle existe dans le texte source.
- **Ce que je ne lui déléguerais jamais.**
  - **La décision de répondre ou non, et le prix**, qui engagent la capacité de production et la marge.
  - **La validation finale d'une donnée avant d'agir dessus.**
  - **Tout envoi au nom de Meet My Mama** : une réponse d'appel d'offres engage juridiquement.
  - **Le récit des Mamas.** Leur histoire leur appartient. Elle ne se génère pas : elle se recueille, avec leur accord.

---

*Code, données et rapport qualité : dépôt GitHub, avec `README.md` pour relancer le pipeline en deux commandes.*
