# Estrattore TikTok per TESI LM

Nuovo punto di ingresso autonomo per il progetto di orsoFra:
https://github.com/orsoFra/python_tiktok-research-api

Codice originale esaminato al commit `e8f5bbe9c4c657778844058c81766ca2ba903e10`, il 9 novembre 2026.
Questa cartella contiene una nuova implementazione della raccolta video, non una copia
completa del repository. Puoi usarla da sola oppure aggiungerla come sottocartella
al repository originale. Gli script originali non vengono modificati e non servono
per eseguire questa versione. Non vengono raccolti profili, follower o like degli utenti.

## 1. Parti da questi due file

- `config.json`: modifica qui date, filtri e campi da scaricare.
- `estrai_video.py`: esegui questo file; normalmente non devi modificarlo.

Le date di esempio sono il 4 ottobre–4 novembre 2026. I filtri sono soltanto un
esempio didattico, non una selezione validata delle proteste per la tesi.

## 2. Cambia le date

All'inizio di `config.json`:

```json
"start_date": "2026-10-04",
"end_date": "2026-11-04"
```

Il programma interpreta entrambe come date UTC incluse nella raccolta. Produce
due finestre: 4 ottobre–2 novembre e 3–4 novembre. Usa finestre di 30 date
consecutive: questa scelta conservativa rispetta il vincolo API senza saltare
giorni 31 o 29 febbraio. Le converte automaticamente in `20261004`, ecc.
Sono date di pubblicazione, non date di download. Il download ha un timestamp separato.

Puoi sostituirle temporaneamente dal terminale, lasciando intatto il file:

```powershell
python estrai_video.py --start-date 2026-10-01 --end-date 2026-10-31 --dry-run
```

## 3. Formula la query

`query` seleziona i video; `fields` seleziona le informazioni da ricevere.
La configurazione di esempio chiede:

**Account registrato in Italia o Francia E (descrizione con “protesta” O hashtag “manifestation”).**

Una condizione è un oggetto come questo:

```json
{"operation": "EQ", "field_name": "hashtag_name", "field_values": ["fridaysforfuture"]}
```

Gli hashtag vanno inseriti senza `#`. `keyword` cerca nella descrizione, non
automaticamente nell'audio; TikTok documenta matching testuale approssimato.
`region_code` è il paese di registrazione dell'account: non è una geolocalizzazione.

| Elemento | Significato |
|---|---|
| `and` | Tutte le condizioni elencate |
| `or` | Almeno una delle condizioni elencate |
| `not` | Nessuna delle condizioni elencate |
| `EQ` | Confronto con un valore |
| `IN` | Confronto con uno dei valori nella lista |
| `GT`, `GTE` | Maggiore, maggiore o uguale |
| `LT`, `LTE` | Minore, minore o uguale |

Il formato è JSON: virgolette doppie, niente commenti, niente virgola dopo l'ultimo elemento.
I valori dei filtri sono stringhe, anche per numeri: `["1000"]`.
I gruppi sono liste piatte; questa versione non accetta gruppi annidati.

### Esempio A: uno qualunque di due hashtag, senza vincolo geografico

Sostituisci l'intero oggetto `query` con:

```json
"query": {
  "and": [
    {"operation": "IN", "field_name": "hashtag_name", "field_values": ["fridaysforfuture", "climatestrike"]}
  ]
}
```

### Esempio B: video di un account

```json
"query": {
  "and": [
    {"operation": "EQ", "field_name": "username", "field_values": ["nome_account"]}
  ]
}
```

Sostituisci `nome_account` con lo username effettivo senza `@`.

### Esempio C: due hashtag entrambi presenti

```json
"query": {
  "and": [
    {"operation": "EQ", "field_name": "hashtag_name", "field_values": ["climate"]},
    {"operation": "EQ", "field_name": "hashtag_name", "field_values": ["protest"]}
  ]
}
```

## 4. Prova senza accesso API

Apri questa cartella in VS Code e il terminale integrato:

```powershell
python estrai_video.py --dry-run
```

Non serve installare dipendenze per questa anteprima. Mostra URL, campi e corpo
JSON della prima richiesta di ciascuna finestra; non scarica dati e non consuma quota.
Non è una simulazione di risultati né una verifica dell'autorizzazione TikTok.

## 5. Esegui la raccolta su Windows

Richiede Python 3.10 o successivo e accesso approvato alla Research API.
Non basta un normale account sviluppatore.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Apri `.env` e sostituisci i due segnaposto con le tue credenziali.
Non inviarle in chat o inserirle nel codice. Sono riconosciuti anche i nomi
`C_KEY` e `C_SECRET` usati dal repository originale. Le variabili d'ambiente
già impostate hanno precedenza su `.env`.

```powershell
.venv\Scripts\python.exe estrai_video.py --dry-run
.venv\Scripts\python.exe estrai_video.py
```

## 6. Cosa succede durante una richiesta

Il programma ottiene un token dall'endpoint OAuth, poi esegue un POST
all'endpoint video con `params={"fields": ...}` e `json=body`.
Il corpo contiene query, date, max_count e is_random=false.
Il token è nell'header Authorization, mai nei file di output.
Per le pagine successive usa cursor/search_id della risposta, finché has_more
diventa false. A ogni nuova finestra ricomincia senza cursor/search_id.

- `max_count=100`: al massimo 100 video per risposta, non per raccolta.
- `max_requests=100`: tetto locale di tentativi video dell'intera esecuzione,
  inclusi retry; non misura la quota residua condivisa con altri programmi.
- Le chiamate OAuth non rientrano in quel contatore locale.
- Il limite può interrompere la raccolta prima di aver esaurito i risultati.
- Questa versione non implementa il campionamento casuale.

## 7. Risultati e limiti

Ogni esecuzione crea una cartella distinta sotto `output`, accanto a config.json:

| File | Contenuto |
|---|---|
| `config_usata.json` | Configurazione effettiva, incluse sostituzioni CLI |
| `pages/000001.json`, ecc. | Richiesta, risposta originale, data di raccolta |
| `videos.jsonl` | Un video per riga, duplicati rimossi per id nell'esecuzione |
| `riepilogo.json` | Stato, conteggi e finestre completate |

Gli ID nei dati originali non vengono alterati. Quando li importi in strumenti
che convertono i numeri in floating point (per esempio un foglio di calcolo),
trattali come testo per evitare perdita di precisione.

`completed` significa che tutte le finestre hanno raggiunto has_more=false:
non dimostra la completezza rispetto a tutti i video esistenti sulla piattaforma.
`partial_budget` significa che il tetto locale ha interrotto la raccolta (exit code 2).
`error` e `interrupted` indicano errore o interruzione: le pagine già scritte restano.
Non è implementata la ripresa automatica: rilanciare crea una nuova raccolta,
può ripetere richieste e consumare altra quota. La deduplicazione non attraversa
esecuzioni diverse. Per volumi elevati, l'insieme degli ID unici usa memoria RAM.
I retry di rete possono ripetere una richiesta che il server aveva già elaborato.

Le statistiche non sono necessariamente in tempo reale; contenuti nuovi possono
arrivare nell'indice con ritardo. La selezione di hashtag e parole chiave va validata
su un campione prima di usarla come dataset della tesi.

## 8. Differenze dal codice originale

| Nel repository esaminato | In questa implementazione |
|---|---|
| TT_extractor.py costruisce mesi con calc_dates; omette 31 e 29 febbraio | Date esplicite e finestre continue |
| range(begin_year, finish_year) esclude l'anno finale | Intervallo di date esplicito |
| --day identifica la raccolta/cartella | Date di pubblicazione distinte dai timestamp di raccolta |
| TT_weekly.py contiene anni e settimane nel codice | Tutto l'intervallo in config.json |
| QUERY costruita dentro data_collection in tiktok_video_hash_data.py | Query visibile e modificabile in config.json |
| Richiesta video con data= e query serializzata separatamente | Corpo JSON unico |
| Alcuni rami ignorano un hashtag generico | Condizioni esplicite, nessuna interpretazione speciale |
| Aggiornamento token basato sul tempo CPU | Scadenza expires_in e orologio monotono |
| Paginazione con controllo iniziale i == 1000 inefficace | Arresto esplicito su has_more=false |

## 9. Verifica

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Test offline con risposte simulate: date/bisestili, paginazione, reset tra finestre,
deduplicazione, pagine vuote con seguito, budget, errori API, richiesta JSON,
scadenza token e anteprima senza rete. Nessuna chiamata autenticata è stata eseguita
durante la preparazione: serve la prova reale con le tue credenziali approvate.

Documentazione consultata il 9 novembre 2026:
- https://developers.tiktok.com/docs/en/research-api-specs-query-videos
- https://developers.tiktok.com/docs/en/research-api-get-started
- https://developers.tiktok.com/docs/en/research-api-faq
