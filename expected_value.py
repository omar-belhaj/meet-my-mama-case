"""
Valeur attendue des 5 opportunités retenues (partie 4 du cas).

Toutes les hypothèses sont des paramètres explicites : on les ajustera dès que Meet My Mama
partagera ses vrais chiffres (panier moyen, taux de transformation sur appels d'offres).

  valeur captable  = montant estimé de l'avis x taux de consommation
  valeur attendue  = valeur captable x probabilité de gagner
  nb prestations   = valeur captable / panier moyen
"""
import pandas as pd

PANIER_MOYEN = 2_500  # EUR HT par prestation (hypothèse : ~80 convives x ~30 EUR HT)
CONSO_ACCORD_CADRE = 0.60  # part du montant maximum réellement commandée (hypothèse prudente)

# idweb : (montant retenu EUR HT, taux de consommation, proba de gagner, justification)
TOP5 = {
    "26-102109": (340_000, CONSO_ACCORD_CADRE, 0.12,
                  "Villeneuve-la-Garenne (92), proche de Nanterre ; gros volume donc plus de concurrence"),
    "26-96565": (160_000, 0.80, 0.15,
                 "Banquet des aînés du CCAS de Chevilly-Larue : volume ferme ; animation à sous-traiter"),
    "26-98789": (90_000, CONSO_ACCORD_CADRE, 0.20,
                 "Vœux du Maire d'Élancourt : besoin récurrent et visible ; montant accessible"),
    "26-91467": (50_000, CONSO_ACCORD_CADRE, 0.20,
                 "Romainville (93) : traiteurs ET boulangeries artisanales, la valeur porte sur la part traiteur"),
    "26-99962": (20_000, 1.00, 0.20,
                 "Banquet seniors de Créteil (janv. 2027) : montant non publié, hypothèse 500 x 40 EUR HT"),
}


def main() -> pd.DataFrame:
    opp = pd.read_csv("output/opportunites_boamp.csv")
    opp = opp[opp["idweb"].isin(TOP5)].set_index("idweb")
    rows = []
    for idweb, (montant, conso, p, why) in TOP5.items():
        o = opp.loc[idweb]
        captable = montant * conso
        rows.append({
            "acheteur": o["acheteur"], "date_limite": str(o["deadline"])[:10], "priorite_script": o["priorite"],
            "montant_HT": montant, "montant_publie": pd.notna(o["valeur_estimee"]), "conso": conso,
            "valeur_captable": captable, "nb_prestations": round(captable / PANIER_MOYEN),
            "p_gain": p, "valeur_attendue": round(captable * p), "hypothese": why,
        })
    df = pd.DataFrame(rows).sort_values("date_limite")
    print(df.drop(columns="hypothese").to_string(index=False))
    print(f"\nValeur attendue totale : {df['valeur_attendue'].sum():,.0f} EUR HT (sur la durée des marchés)")
    # Sensibilité : que vaut le portefeuille si le taux de gain est divisé ou multiplié par 2 ?
    for k in (0.5, 2):
        print(f"  si p x {k} : {(df['valeur_captable'] * (df['p_gain'] * k).clip(upper=1)).sum():,.0f} EUR HT")
    df.to_csv("output/top5_valeur_attendue.csv", index=False, encoding="utf-8-sig")
    return df


if __name__ == "__main__":
    main()
