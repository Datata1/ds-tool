# Profil (`data/<welt>/profil.yaml`)

Persönliche Vorgaben pro Welt. `ap init` legt die Datei an, `/profil-einrichten` füllt sie im
Gespräch. Jede Operation übernimmt die Werte, und `ap op check` meldet Abweichungen. Die Datei liegt
unter `data/` und kommt **nicht** ins Git-Repo.

| Feld | Bedeutung | Beispiel |
|---|---|---|
| `world`, `server`, `timezone` | Welt | `de260`, `die-staemme.de`, `Europe/Berlin` |
| `player` | Wer plant | `MeinName` |
| `own_tribes` | Eigener Stamm, dessen Dörfer geplant werden | `[ABC]` |
| `allied_tribes` | Verbündete/Wing: deren Pläne werden nur gelesen | `[ABC2]` |
| `send_window` | Losschick-Zeitfenster | `{start: "00:00", end: "23:59:59"}` |
| `off_min_pop` | Volle Off ab … Off-Plätzen (Axt 1, LKav 4, Ramme 5, Kata 8) | `7000` |
| `fusion_min_pop` | Kleinster Fusionsoff-Teil | `1000` |
| `noble_escort` | Begleitschutz pro AG | `{axe: 100}` |
| `fake_unit` | Fake-Einheit | `ram` |
| `home_guard` | Fakeschutz (bleibt daheim) | `{spear: 50, sword: 50, spy: 51}` |
| `off_send_gap_s` | Sicherheitsabstand Off vor AG (s) | `2` |
| `allow_second_break` | Sekunde brechen erlaubt | `true` |
| `max_troop_age_hours` | Truppendaten veraltet ab | `24` |
| `preferences` | Freitext-Vorlieben, die der Agent beachten muss | siehe unten |

```yaml
preferences:
  - "Gleiche Sekunde für Offs und AGs bevorzugt, nur notfalls Sekunde brechen."
  - "Fakes nie aus Dörfern mit eingehenden Angriffen."
  - "Bei echten Adelungen immer Flexdeff einplanen."
```

Beispiel: [examples/profil.beispiel.yaml](../examples/profil.beispiel.yaml)
