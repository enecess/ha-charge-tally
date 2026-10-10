# Charge Tally

[English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Polski](README.pl.md) · **Italiano**

Registra energia e costi delle ricariche per punto e identità in Home Assistant, e verifica come è stato calcolato ogni importo. Charge Tally usa i sensori di energia o potenza già disponibili: gestisce la contabilizzazione, senza accendere o spegnere il caricatore.

- Un registro contabile per più punti, con identità condivise per veicoli, conducenti o familiari.
- Misurazione da energia cumulativa, energia calcolata dalla potenza oppure energia misurata con rilevamento tramite potenza.
- Prezzi fissi, dinamici o a fasce giornaliere, anche nulli o negativi.
- Rilevamento automatico oppure avvio e fine dalla scheda o dalle automazioni di Home Assistant.
- Stato in tempo reale, statistiche odierne, mensili, annuali, complessive o personalizzate e grafici raggruppati per intervallo.
- Inserimento di registrazioni passate, modifica di quelle terminate, riassegnazione, annullamento, segmenti di contabilizzazione e revisioni.
- Gestione dei punti e delle identità archiviati, con eliminazione permanente dei dati non più necessari.

Usa **Impostazioni → Dispositivi e servizi → Charge Tally** per la configurazione e la scheda **Charge Tally** nella dashboard per le registrazioni. La scheda riunisce più sezioni in una pagina; dettagli e modifiche si aprono in finestre di dialogo.

> Segnaposto immagine 01: Scheda completa con punti di ricarica, statistiche ed elenco delle registrazioni.

## Comportamento attuale della scheda e della contabilità

All’apertura sono espansi solo i controlli di ricarica. Statistiche e registrazioni sono inizialmente chiuse. Gli aggiornamenti conservano le sezioni aperte e lo stato dei controlli; ricaricare la pagina ripristina la vista iniziale. Grafico e cronologia vengono caricati aprendo la rispettiva sezione.

I grafici raggruppano Oggi per ora, Questo mese per giorno, Quest’anno per mese e Totale per anno. Per un intervallo personalizzato conta la differenza tra le date del calendario locale: fino a 2 giorni per ora, fino a 90 giorni per giorno, fino a 730 giorni per mese e oltre per anno. Si applicano il fuso del registro e i cambi dell’ora legale. Grafici e riepilogo coprono lo stesso intervallo; un costo sconosciuto resta sconosciuto.

I segmenti di fatturazione nelle anteprime e nei dettagli uniscono intervalli adiacenti con la stessa base di calcolo, tariffa e qualità. Descrivono la fattura, non ogni singola lettura. Le statistiche temporali continuano a usare gli intervalli di misura originali. La cronologia delle modifiche salva un’istantanea all’avvio, alla fine e per modifiche esplicite, comprese riassegnazione e annullamento. I campioni correnti aggiornano la registrazione senza altre istantanee; i numeri di revisione possono quindi avere salti.

Rimuovere la configurazione di un punto conserva le registrazioni non terminate. In **Configura → Gestisci dati archiviati → Punti di ricarica archiviati**, seleziona il punto rimosso, controlla il numero di registrazioni non terminate e i dati coinvolti, quindi conferma esplicitamente l’eliminazione definitiva. Annullare conserva i dati. La pulizia elimina registrazioni, revisioni, campioni e prezzi del punto, ma non i dati Recorder di HA né i backup.

Il formato attuale del registro di sviluppo è cambiato. I formati precedenti non supportati vengono rifiutati senza migrazione o eliminazione automatica. Un registro di test temporaneo potrebbe dover essere ricreato dopo un backup; l’aggiornamento dell’integrazione non esegue questa pulizia.

## Indice

- [Prima di installare](#prima-di-installare)
- [Installare l’integrazione](#installare-lintegrazione)
- [Configurazione iniziale](#configurazione-iniziale)
- [Identità e configurazioni successive](#identità-e-configurazioni-successive)
- [Aggiungere e configurare la scheda](#aggiungere-e-configurare-la-scheda)
- [Le sezioni della scheda](#le-sezioni-della-scheda)
- [Operazioni quotidiane](#operazioni-quotidiane)
- [Aggiungere e modificare registrazioni passate](#aggiungere-e-modificare-registrazioni-passate)
- [Interpretare statistiche e qualità dei dati](#interpretare-statistiche-e-qualità-dei-dati)
- [Entità native e automazioni](#entità-native-e-automazioni)
- [Gestire dati archiviati e valuta](#gestire-dati-archiviati-e-valuta)
- [Aggiornamenti, backup e ripristino](#aggiornamenti-backup-e-ripristino)
- [Risoluzione dei problemi](#risoluzione-dei-problemi)

## Prima di installare

Servono **Home Assistant 2025.3.4 o successivo** e almeno un sensore che misuri il circuito di ricarica. Installa e configura con un account amministratore. L’interfaccia segue la lingua di Home Assistant; questa guida usa le etichette italiane effettive. La posizione dei menu generali di HA può variare tra versioni.

| Dati disponibili | **Modalità di acquisizione dell’energia** | Utilizzo |
| --- | --- | --- |
| Energia cumulativa in Wh, kWh o MWh | **Solo energia** | Contabilizza le letture; avvia e termina dalla scheda o dalle automazioni |
| Potenza in W o kW | **Solo potenza (Integral nativo)** | Crea automaticamente un aiutante HA per calcolare l’energia; consente il rilevamento automatico |
| Energia cumulativa e potenza | **Energia e potenza** | Misura con l’energia e rileva con la potenza, senza contare due volte l’energia |

L’energia cumulativa deve normalmente aumentare, oppure ripartire da zero dopo un azzeramento. Non deve essere un valore mobile come «energia dell’ultima ora». I sensori devono essere identificati correttamente come energia o potenza in HA e fornire valori numerici validi non negativi. Una fonte non può essere assegnata a più punti.

Per prezzi dinamici prepara un sensore nella valuta del registro. Per ricostruire registrazioni dallo storico, verifica che HA registri i sensori e conservi ancora le date necessarie.

## Installare l’integrazione

### Metodo 1: HACS

Se necessario, segui prima le [istruzioni ufficiali di installazione di HACS](https://hacs.dev/docs/use/download/download/).

**Aggiungi a HACS con un clic:**

[![Apri Charge Tally in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=enecess&repository=ha-charge-tally&category=integration)

Fai clic sul pulsante, inserisci o conferma l’indirizzo di Home Assistant, quindi aggiungi o apri Charge Tally in HACS. Prosegui dal passaggio 3 qui sotto per scaricare, riavviare e aggiungere l’integrazione, oppure parti dal passaggio 1 per aggiungere il repository manualmente.

1. Apri **HACS**, il menu in alto a destra e **Repository personalizzati**.
2. Aggiungi `https://github.com/enecess/ha-charge-tally` con tipo **Integrazione**.
3. Cerca **Charge Tally**, aprilo e scarica la versione desiderata.
4. **Riavvia Home Assistant**.
5. Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione** e cerca **Charge Tally**.
6. Prosegui con «Configurazione iniziale». Il download da HACS non crea automaticamente il registro o i punti.

> Segnaposto immagine 02: Repository personalizzati HACS, pagina di download e ricerca in Aggiungi integrazione.

### Metodo 2: Installazione manuale

1. Scarica ed estrai questo repository, quindi trova `custom_components/charge_tally`.
2. Apri la cartella di configurazione di Home Assistant che contiene `configuration.yaml`.
3. Crea `custom_components` se manca e copiaci l’intera cartella `charge_tally`, comprese tutte le sottocartelle.
4. Verifica che il percorso finale sia `custom_components/charge_tally/manifest.json`, senza un ulteriore livello con il nome del repository.
5. **Riavvia Home Assistant**, poi apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Charge Tally**.

La scheda è inclusa nell’integrazione: non serve installare separatamente un componente frontend da HACS. Se l’integrazione non compare, controlla cartelle e riavvio, poi aggiorna la pagina e consulta i log di HA.

## Configurazione iniziale

### 1. Creare il registro

In **Registro contabile Charge Tally**, inserisci la **Valuta**, per esempio CNY, EUR o USD. Ogni istanza HA usa un solo registro, con una valuta comune a tutti i punti e alle registrazioni.

- La valuta è modificabile quando non restano punti, anche archiviati, né dati contabili. Le sole identità non la bloccano.
- Aggiungere un punto la blocca, anche prima della prima ricarica.
- Eliminare la configurazione conserva lo storico. Occorre eliminare completamente tutti i punti e i dati collegati per cambiarla di nuovo.
- Non avviene alcuna conversione. Quando aggiungi nuovamente un’integrazione rimossa, seleziona prima la valuta originale del registro conservato.

> Segnaposto immagine 03: Registro contabile Charge Tally e indicazioni sulla valuta.

### 2. Aggiungere un punto

Le versioni HA che supportano la prosecuzione automatica aprono la finestra del punto dopo la creazione del registro. Altrimenti usa **Impostazioni → Dispositivi e servizi → Charge Tally → Aggiungi punto di ricarica**.

In **Punto di ricarica**, inserisci il **Nome**, per esempio «Garage», e scegli la **Modalità di acquisizione dell’energia**. Ogni punto rappresenta un circuito misurato separatamente.

### 3. Scegliere le fonti di misurazione

In **Fonti di misurazione**, espandi **Misurazione e rilevamento**:

| Campo | Cosa indicare |
| --- | --- |
| **Sensore di energia cumulativa** | Sensore cumulativo del circuito; assente in **Solo potenza (Integral nativo)** |
| **Sensore di potenza** | Sensore di potenza del circuito; assente in **Solo energia** |
| **Il contatore può azzerarsi** | Lascia attivo se può tornare a zero; una lettura in calo segnala un intervallo di azzeramento incompleto |
| **Intervallo massimo di ripartizione (secondi)** | Predefinito: 600 secondi; intervalli più lunghi sono lacune da verificare |
| **Rilevamento automatico della ricarica** | Disponibile nelle modalità con potenza; attivandolo si passa ai parametri di rilevamento |

### 4. Impostare il rilevamento automatico (facoltativo)

Dopo aver attivato **Rilevamento automatico della ricarica**, configura **Rilevamento automatico**:

- **Soglia di avvio (W)**: una potenza uguale o superiore avvia la conferma.
- **Durata di avvio (secondi)**: la condizione deve durare almeno questo tempo; predefinito: 30 secondi.
- **Soglia di fine (W)**: una potenza inferiore avvia la conferma della fine; deve essere minore della soglia di avvio.
- **Durata di fine (secondi)**: trascorso questo tempo con la condizione soddisfatta, termina la registrazione; predefinito: 300 secondi.

Scegli soglie adatte alla potenza reale di standby e ricarica. Alla conferma, l’orario viene riportato al momento iniziale della condizione. Una pausa più breve della durata di fine resta nella stessa registrazione. Seleziona l’identità prima che salga la potenza: viene memorizzata quando inizia la conferma dell’avvio.

Il rilevamento è facoltativo: puoi usare **Avvia contabilizzazione manualmente** e **Termina contabilizzazione**.

> Segnaposto immagine 04: Misurazione e rilevamento e finestra Rilevamento automatico.

### 5. Configurare i prezzi

Le opzioni di **Modalità di prezzo** differiscono leggermente dai titoli delle finestre successive:

| Opzione | Finestra successiva | Campi |
| --- | --- | --- |
| **Fisso** | **Prezzo fisso** | **Prezzo per kWh**, nella valuta del registro |
| **Sensore dinamico** | **Prezzo dinamico** | **Sensore del prezzo** e, se necessario, **Unità confermata** |
| **Fasce orarie giornaliere** | **Programma giornaliero delle fasce orarie** | Fasce di prezzo che coprono una giornata |

Prezzi fissi e a fasce possono essere nulli o negativi. Quelli dinamici possono usare la valuta del registro per Wh, kWh o MWh: le unità vengono normalizzate, le valute non convertite. **Unità confermata** serve solo se la fonte non ha un’unità; non può sostituire una valuta o unità esistente ma errata.

Per **Programma giornaliero delle fasce orarie**:

1. In **Azione**, scegli **Aggiungi fascia**.
2. In **Modifica fascia di prezzo**, compila **Ora di inizio**, **Ora di fine (24:00 = fine della giornata)** e **Prezzo per kWh**.
3. Aggiungi le altre fasce. Per cambiarne o eliminarne una, seleziona **Fascia**, poi **Modifica fascia** o **Rimuovi fascia**.
4. Quando la giornata è interamente coperta, scegli **Completa programma**.

Usa `HH:MM`, per esempio `00:00–08:00`, `08:00–22:00`, `22:00–24:00`. Sono ammesse fasce oltre mezzanotte, come `22:00–06:00`. Non sono ammessi vuoti, sovrapposizioni o estremi uguali; `00:00–24:00` copre l’intera giornata. Il programma si ripete ogni giorno, senza distinzione tra feriali e fine settimana.

> Segnaposto immagine 05: Modalità di prezzo, conferma dell’unità dinamica, programma giornaliero e modifica di una fascia.

### 6. Verificare statistiche e riepilogo

In **Statistiche per periodo e riepilogo**, verifica nome, modalità di acquisizione e prezzo. In **Periodi delle statistiche energetiche**, seleziona **Giornaliero / Mensile / Annuale**. Sono tutti selezionati inizialmente; puoi anche non selezionarne nessuno.

Queste opzioni creano ulteriori aiutanti energetici nativi. Non determinano la disponibilità delle statistiche della scheda o delle identità. Al termine, verifica che il punto compaia nell’integrazione, i sensori funzionino e non vi siano richieste di riparazione degli aiutanti.

> Segnaposto immagine 06: Statistiche per periodo e riepilogo e pagina dell’integrazione configurata.

## Identità e configurazioni successive

In **Impostazioni → Dispositivi e servizi → Charge Tally**, usa:

| Voce | Funzione |
| --- | --- |
| **Aggiungi punto di ricarica** | Aggiungere un altro circuito misurato separatamente |
| **Configura punto di ricarica** | Modificare nome, sensori, rilevamento, prezzi e periodi |
| **Aggiungi identità condivisa** | Creare un’identità per veicolo, persona o altro soggetto |
| **Configura identità** | Cambiare nome o **Abilitata** |
| **Configura** dell’integrazione principale | Aprire **Impostazioni del registro** e **Gestisci dati archiviati**; **Collegamenti identità NFC** |

**Identità condivisa** contiene **Nome** e **Abilitata**. Le identità sono comuni a tutti i punti; i nomi configurati devono essere univoci. L’identità integrata **Unassigned** raccoglie le registrazioni non assegnate e mantiene questo nome inglese nei selettori.

Rinominare non cambia l’attribuzione storica. Deselezionare **Abilitata** impedisce nuove selezioni ma conserva lo storico. Eliminare la configurazione conserva anch’esso lo storico, rendendo possibile la successiva rimozione permanente tramite archivi. Disabilitare ed eliminare la configurazione sono operazioni diverse.

Prima di cambiare misurazione o rilevamento, termina la registrazione attiva e attendi la fine di **Conferma della ricarica in corso / Conferma della fine in corso**. I nuovi prezzi valgono dal momento della modifica e non ricalcolano gli importi precedenti. Termina la registrazione anche prima di eliminare un punto: rimuoverne la configurazione non conclude automaticamente una ricarica in corso.

> Segnaposto immagine 07: Configurazione dell’identità e voci separate per punti e integrazione principale.

## Aggiungere e configurare la scheda

1. Configura almeno un punto, poi apri la dashboard desiderata.
2. Entra in modifica. Con il layout a sezioni usa il pulsante più nella sezione; negli altri layout usa **Aggiungi scheda**.
3. Cerca **Charge Tally** tra i tipi di scheda e selezionala.
4. Imposta l’editor visuale, salva la scheda e termina la modifica della dashboard.

| Campo dell’editor | Funzione |
| --- | --- |
| **Titolo** | Titolo personalizzato; vuoto mostra Charge Tally |
| **Punto di ricarica** | Selezione iniziale del punto, oppure **Tutti** |
| **Filtro per identità** | Selezione iniziale dell’identità, oppure **Tutti** |
| **Mostra registrazioni** | Mostra/nasconde l’elenco e **Aggiungi registrazione passata** |
| **Mostra grafico** | Mostra/nasconde il grafico senza cambiare i totali |

Puoi aggiungere più schede con selezioni iniziali diverse. Sono filtri di visualizzazione, non autorizzazioni: ciascun utente accede solo ai dati consentiti da HA. La scheda supporta italiano, inglese, cinese semplificato, tedesco, francese e polacco, e segue il tema.

> Segnaposto immagine 08: Aggiunta della scheda e cinque impostazioni dell’editor visuale.

### Se la scheda non compare

Verifica che l’integrazione sia caricata e aggiorna il browser. Se le risorse della dashboard sono gestite dall’interfaccia, la registrazione della scheda è normalmente automatica.

Se serve intervenire, apri **Risorse** dal menu di **Impostazioni → Dashboard**. Attiva **Modalità avanzata** nel profilo se la voce è nascosta. Aggiungi la risorsa e aggiorna:

| Campo | Valore |
| --- | --- |
| URL | `/charge_tally/charge-tally-card.js?v=0.1.2-6` |
| Tipo di risorsa | **Modulo JavaScript** |

Se esiste già lo stesso percorso, aggiornalo senza duplicarlo. Se gestisci le risorse in YAML, registra lì lo stesso URL e tipo modulo; non installare una seconda copia. Vedi la [documentazione delle dashboard di Home Assistant](https://www.home-assistant.io/dashboards/dashboards/).

## Le sezioni della scheda

### Connessione e filtri

Accanto al titolo appare **Connesso** oppure **Disconnesso · in attesa di dati aggiornati**. Usa **Riprova** quando la connessione torna disponibile; non considerare una visualizzazione precedente come risultato contabile aggiornato.

**Punto di ricarica** e **Filtro per identità** si applicano a statistiche ed elenco. Il punto selezionato determina anche i pannelli in tempo reale; il filtro per identità non cambia l’identità selezionata sul punto. Gli elementi conservati possono essere **Archiviato**. I punti archiviati hanno storico ma non controlli in tempo reale per avviare ricariche. Anche identità disabilitate possono avere questa indicazione; l’eliminazione permanente dipende dalle condizioni della gestione archivi.

### Pannelli dei punti in tempo reale

Il pannello distingue lo stato della contabilizzazione da **Potenza** e **Rilevamento**. **Nessuna contabilizzazione in corso**, **Contabilizzazione manuale in corso** e **Contabilizzazione automatica in corso** descrivono il registro; una registrazione attiva non implica che il caricatore stia assorbendo corrente. Il rilevamento indica separatamente attesa, conferma, pausa durante una registrazione manuale, dati non disponibili o attesa del calo di potenza.

Durante la conferma dell’avvio, **Identità fissata per la registrazione automatica** mostra l’identità memorizzata all’inizio della conferma. **Identità della prossima registrazione / registrazione manuale** vale per la prossima registrazione automatica o per un avvio manuale immediato, senza cambiare l’identità fissata del candidato o quella della registrazione attiva.

Ogni punto corrente mostra nome, stato, **Potenza**, **Prezzo attuale** e stato di **Rilevamento**. Valori non disponibili possono essere vuoti. Qui Rilevamento è solo un’indicazione: per cambiarlo usa la configurazione o l’interruttore nativo **Rilevamento**.

| Contenuto | Significato |
| --- | --- |
| **Identità selezionata** | Attribuzione della prossima ricarica quando non vi sono registrazioni attive |
| **Questa registrazione** | Identità della registrazione attiva |
| **Identità della prossima registrazione** | Prepara la successiva senza cambiare quella corrente |
| **Contabilizzazione in corso · Totale attuale** | Energia, costo, inizio, durata e qualità attuali |
| **Dettagli** | Apre la registrazione corrente |
| **Cambia identità della registrazione** | Corregge l’attribuzione corrente |
| **Avvia contabilizzazione manualmente / Termina contabilizzazione** | Inizia/termina la contabilizzazione all’ora attuale |

> Segnaposto immagine 09: Ricarica attiva, identità corrente e successiva, costo provvisorio e pulsanti.

### Statistiche e grafici

In **Statistiche delle registrazioni → Periodo delle statistiche**, scegli **Oggi / Questo mese / Quest’anno / Dall’inizio / Intervallo personalizzato**. Per date personalizzate, indica **Inizio** e **Fine (esclusa)**, poi **Applica intervallo**. Per tutto il 1° settembre, per esempio, imposta inizio al 1° e fine al 2 settembre.

Il riepilogo mostra **Energia**, **Costo**, **Attive / completate** e qualità. **Aggiorna** carica i risultati più recenti. Il grafico raggruppa secondo l’intervallo scelto; **Misura del grafico** alterna **Energia / Costo**. Espandi **Dettagli** sotto il grafico per la tabella per intervalli.

> Segnaposto immagine 10: Statistiche, date personalizzate, Misura del grafico e Dettagli raggruppati espansi.

### Registrazioni · tutte le date

L’elenco contiene registrazioni attive e terminate, ordinate dall’inizio più recente, 25 per pagina. Usa **Precedente / Successiva**. Ogni riga mostra punto, identità, inizio, stato, energia, costo e qualità; fai clic sulla riga per i dettagli.

Valgono solo i filtri per punto e identità: **le date delle statistiche non filtrano questo elenco**. Le registrazioni precedenti restano visibili anche con Oggi selezionato. **Aggiungi registrazione passata** è accanto al titolo; l’elenco vuoto mostra **Nessuna registrazione**.

> Segnaposto immagine 11: Registrazioni · tutte le date, aggiunta, righe e paginazione.

## Operazioni quotidiane

### Avviare e terminare manualmente

1. Seleziona l’identità e **Avvia contabilizzazione manualmente**; durante la conferma dell’avvio, usa **Avvia contabilizzazione ora**.
2. Verifica **Contabilizzazione manuale in corso** e i totali attuali. L’avvio manuale immediato usa l’identità attualmente selezionata e cancella il candidato automatico.
3. Premi **Termina contabilizzazione** e controlla la registrazione nell’elenco.

Questi pulsanti registrano gli orari senza comandare il caricatore. Una registrazione avviata manualmente deve essere terminata esplicitamente dalla scheda o da un’azione di automazione. Il rilevamento automatico rimane in pausa e non la termina mai, nemmeno a potenza zero. Per iniziare serve una lettura iniziale valida dell’energia; una registrazione esistente può essere terminata anche se le misure diventano indisponibili.

### Rilevare automaticamente la ricarica

Con il rilevamento configurato e attivo, la sequenza può essere **Conferma della ricarica in corso → Monitoraggio di una registrazione automatica → Conferma della fine in corso → In attesa del rilevamento automatico**. Se la condizione di potenza cessa durante la conferma, la conferma in sospeso viene annullata. La conferma automatica usa l’identità fissata del candidato anche se la selezione cambia. Puoi terminare in anticipo una registrazione automatica con **Termina contabilizzazione manualmente**, oppure **Termina contabilizzazione ora** durante la conferma della fine.

Dopo una fine esplicita, il rilevamento normalmente attende una potenza inferiore alla soglia di fine. Può riprendere subito solo se l’ultima misura valida di bassa potenza non è successiva al comando di fine, la sua età non supera la durata di validità impostata in **Intervallo massimo di ripartizione (secondi)** e non è stata invalidata da dati indisponibili o da un riavvio. Misure alte, mancanti, future o obsolete non rimuovono il blocco. Dopo una potenza `unknown` o indisponibile occorre una successiva misura valida sotto la soglia. Durante il blocco resta possibile avviare manualmente una registrazione.

Prima di sospendere con **Rilevamento**, termina le registrazioni attive e le conferme in sospeso. Se mancano le soglie, apri **Configura punto di ricarica**.

### Consultare dettagli e revisioni

I dettagli comprendono attribuzione, energia, costo, orari, fuso contabile, **Stato**, **Origine**, **Revisione**, nota e qualità.

- **Segmenti di contabilizzazione** mostra tempi, energia, costo e **Qualità dei dati** per segmento, utile per verificare mezzanotte e variazioni di prezzo.
- **Storico delle revisioni** mostra identità, stato, importi e note precedenti. È una traccia di verifica; non esiste un pulsante di ripristino della revisione.
- Le registrazioni attive consentono **Cambia identità della registrazione**; solo quelle terminate mostrano **Modifica registrazione** e **Annulla registrazione**.

> Segnaposto immagine 12: Registrazione terminata, segmenti, revisioni espanse e azioni.

### Correggere l’identità

Nei dettagli scegli **Cambia identità della registrazione**, seleziona **Identità assegnata**, poi **Salva anteprima**. È l’etichetta effettiva del pulsante di conferma: in questa finestra non serve una fase separata **Anteprima delle modifiche**. L’intera registrazione cambia attribuzione senza ricalcolare energia o costo.

### Annullare una registrazione errata

Su una registrazione terminata scegli **Annulla registrazione**, verifica e premi **Conferma annullamento**. Esce dalle statistiche e dall’elenco ordinario, ma resta nel registro con le revisioni. Non vi sono pulsanti per mostrare registrazioni annullate o ripristinarle. L’annullamento non è eliminazione permanente.

## Aggiungere e modificare registrazioni passate

**Aggiungi registrazione passata** apre **Nuova registrazione passata**. Per modificare, apri una registrazione terminata e scegli **Modifica registrazione**.

1. Verifica **Fuso orario contabile**, **Punto di ricarica** e **Identità assegnata**. Per nuove registrazioni servono un punto corrente e un’identità abilitata. Un punto archiviato non può riceverne di nuove anche se appare nell’elenco. In modifica il punto originale non può essere cambiato.
2. Inserisci data e ora di **Inizio** e **Fine (esclusa)**; la fine deve essere successiva all’inizio.
3. Compila o lascia vuota l’energia manuale e scegli la base di costo descritta sotto.
4. Aggiungi eventualmente una **Nota**, fino a 2000 caratteri.
5. Premi **Anteprima delle modifiche**. In **Anteprima · verifica prima di salvare**, controlla importi, segmenti, qualità e **Copertura delle misurazioni**. Le modifiche mostrano anche **Prima / Dopo**.
6. Se non ci sono sovrapposizioni, premi **Salva anteprima**. Cambiare il modulo richiede una nuova anteprima; **Chiudi** non salva.

| Campo o opzione | Comportamento |
| --- | --- |
| Nuova registrazione: **Energia manuale (kWh, vuoto: usa lo storico)** | Vuoto usa le misurazioni disponibili; un valore indica l’energia totale |
| Modifica: **Energia manuale (kWh, vuoto: mantieni la base esistente)** | Vuoto conserva la base e non cancella un precedente valore manuale |
| **Base di calcolo del costo → Usa lo storico e i prezzi disponibili** | Predefinito per nuove registrazioni; dipende dai dati realmente disponibili |
| **Base di calcolo del costo → Mantieni la base di calcolo esistente** | Predefinito in modifica; cambiare solo la nota non ricalcola i prezzi |
| **Base di calcolo del costo → Costo totale inserito manualmente** | Attiva **Costo totale inserito manualmente**, anche per importi nulli o negativi |
| **Base di calcolo del costo → In attesa** | Mantiene esplicitamente il costo sconosciuto, non gratuito |

Le registrazioni dello stesso punto non possono sovrapporsi. Un’anteprima con sovrapposizioni non è salvabile. Se non è più aggiornata o la registrazione è cambiata, aggiorna e genera una nuova anteprima.

La ricostruzione dipende dai dati conservati da HA e dal registro: non è garantita per qualunque data passata. Se mancano dati, puoi inserire energia e costo totali dalla ricevuta del caricatore. La ripartizione temporale dei totali manuali genera le indicazioni **Valore impostato manualmente / Stimato**, che ne descrivono la base.

Gli orari usano il fuso contabile indicato, non quello del browser. Per ore locali ripetute al cambio dell’ora legale, scegli **Ora locale ripetuta: seleziona l’istante UTC**. Ore locali inesistenti non possono essere inviate.

> Segnaposto immagine 13: Nuova registrazione passata / Modifica registrazione, base di costo, anteprima e copertura.

## Interpretare statistiche e qualità dei dati

| Indicazione | Significato |
| --- | --- |
| **Provvisorio / In attesa del calcolo definitivo** | Registrazione o confini delle misurazioni non definitivi; nuove letture possono cambiare il risultato |
| **subtotale noto · in attesa** | Solo costo noto, non una fattura completa; sconosciuto non significa zero |
| **Prezzo mancante / Prezzo sconosciuto** | Prezzo non valido nel periodo; controlla valuta, unità, disponibilità e storico |
| **Energia mancante / Intervallo senza misurazioni** | Dati insufficienti o letture troppo distanti; verifica e inserisci valori manuali se necessario |
| **Azzeramento del contatore** | Una lettura in calo ha reso incompleto l’intervallo |
| **Valore impostato manualmente / Stimato** | Valori manuali o ripartizione temporale, non misurazioni effettive in ogni istante |

L’energia viene ripartita nei giorni, mesi e anni in cui si consuma: una ricarica oltre mezzanotte non ricade interamente sul giorno iniziale. Le registrazioni conservano il proprio fuso contabile. Il numero di completate in **Attive / completate** segue l’orario iniziale: una registrazione può contribuire energia a un intervallo senza aumentarne il conteggio delle completate.

Scheda e identità sommano le registrazioni. Le statistiche energetiche native possono includere standby esterno alle registrazioni, quindi i totali possono differire. Modificare aggiorna il registro, non riscrive lo storico del contatore nativo. I grafici dei costi mostrano importi noti; l’arrotondamento visualizzato non cambia la precisione salvata.

## Entità native e automazioni

I dati sono disponibili anche nelle pagine delle entità HA, in altre schede e nelle automazioni. Gli esempi usano il punto «Garage» e l’identità «Auto di famiglia»; i nomi seguono la tua configurazione.

| Entità visibile | Funzione |
| --- | --- |
| **Garage Energia** | Energia cumulativa del punto |
| **Garage Stato** | Stato di ricarica o disponibilità |
| **Garage Energia della registrazione / Garage Costo della registrazione** | Registrazione attiva; senza valore corrente quando inattiva, non la precedente |
| **Garage Identità** | Seleziona l’identità successiva, anche tramite RFID o pulsanti |
| **Garage Rilevamento** | Interruttore di rilevamento nelle modalità con potenza; non alimenta il caricatore |
| **Auto di famiglia energia giornaliera / costo giornaliero, energia mensile / costo mensile, energia annuale / costo annuale, energia totale / costo totale** | Statistiche dell’identità; anche Unassigned dispone delle corrispondenti entità |

Con costi incompleti, le entità native possono non avere un valore completo mentre la scheda mostra il subtotale noto. Gli aiutanti giornalieri/mensili/annuali scelti durante la configurazione hanno uno scopo diverso dalle statistiche delle identità. Non eliminare o modificare manualmente gli aiutanti gestiti dall’integrazione.

Il selettore delle azioni offre **Charge Tally: Avvia contabilizzazione / Termina contabilizzazione / Riassegna l’identità della registrazione**. Avvio e fine usano l’ora corrente del server; non inseriscono orari storici. Per il passato usa la scheda.

I moduli richiedono **ID della richiesta**; fine e riassegnazione richiedono anche **Revisione prevista della registrazione**. Non basta selezionare un dispositivo. Usa un nuovo identificativo per ogni nuova operazione e riutilizza identificativo e campi quando riprovi la stessa. Per cambiare solo la prossima identità usa **Garage Identità**. Se non conosci questi campi di verifica, usa i pulsanti della scheda per contabilizzare direttamente.

## Gestire dati archiviati e valuta

### Rimozione della configurazione, annullamento ed eliminazione

| Operazione | Risultato |
| --- | --- |
| Disabilitare un’identità | Impedisce nuove selezioni; conserva configurazione e storico |
| Eliminare la configurazione di punto/identità | Conserva lo storico e consente la gestione archivi; disabilitare non equivale a eliminare |
| Annullare una registrazione | La esclude dall’elenco ordinario e dalle statistiche, conservando le revisioni |
| Operazione permanente sugli archivi | Elimina oggetti e dati collegati; nessun annullamento dall’interfaccia |

### Eliminare definitivamente un punto archiviato

1. Apri **Configura → Gestisci dati archiviati → Punti di ricarica archiviati** nell’integrazione principale.
2. In **Seleziona oggetto archiviato**, scegli un punto la cui configurazione è stata eliminata.
3. In **Conferma operazione permanente**, verifica oggetto, operazione, record inclusi annullati, revisioni, intervallo UTC, energia e costo noto.
4. Seleziona **Comprendo le conseguenze e confermo l’eliminazione permanente** e invia. **Operazione archivio completata** riporta il numero eliminato.

Vengono eliminati registrazioni, revisioni, campioni e storico dei prezzi del punto: non si nasconde soltanto un nome.

### Rimuovere definitivamente un’identità archiviata

Apri **Configura → Gestisci dati archiviati → Identità archiviate** e scegli l’oggetto. Se esistono registrazioni, in **Trasferisci record dell’identità** seleziona **Identità destinataria**: un’identità abilitata o **Unassigned**. Senza registrazioni si passa direttamente alla conferma.

Tutte le registrazioni, anche annullate, vengono trasferite senza cambiare importi. L’identità originale viene eliminata; le vecchie revisioni conservano il nome per verifica. Unassigned non può essere eliminata. Oggetti in uso o dati cambiati durante la conferma bloccano l’operazione: termina le registrazioni attive o riapri l’anteprima.

La pulizia riguarda solo il registro: **non cancella lo storico Recorder, le statistiche native a lungo termine o i backup di Home Assistant**. I totali della conferma comprendono le registrazioni annullate elencate per descrivere l’ambito; non confrontarli direttamente con le statistiche ordinarie che le escludono.

> Segnaposto immagine 14: Categorie archiviate, selezione, trasferimento dell’identità e conferma permanente.

### Cambiare valuta

Apri **Configura → Impostazioni del registro** nell’integrazione principale. La valuta è modificabile solo senza punti, anche archiviati, né dati contabili. Altrimenti **Valuta del registro contabile bloccata** spiega il limite. Le sole identità non la bloccano.

Per ricominciare con una valuta diversa, esegui un backup, elimina le configurazioni dei punti non più necessari e puliscine i dati dalla gestione archivi, poi riapri le impostazioni. La nuova valuta si sceglie dopo la pulizia; gli importi storici non vengono convertiti.

## Aggiornamenti, backup e ripristino

1. Prima di aggiornare, salva un backup che comprenda la cartella di configurazione HA.
2. Aggiorna da HACS se usato per installare; altrimenti sostituisci l’intera cartella dell’integrazione, mantenendone la struttura.
3. Riavvia HA e aggiorna la dashboard nel browser o nell’app. Se gestisci manualmente le risorse, verifica anche la versione dell’URL indicato sopra.
4. Controlla punti, registrazioni e statistiche; segui l’eventuale riparazione degli aiutanti.

Il registro risiede nella cartella di configurazione HA. Quando Home Assistant crea un backup, l’integrazione prepara una copia coerente del registro. Rimuovere l’integrazione o i file del programma non svuota attivamente il registro; quando la aggiungi di nuovo seleziona la valuta originale. Ripristina configurazione e registro corrispondenti, senza mescolare periodi diversi.

Le icone locali del marchio richiedono **Home Assistant 2026.3 o successivo**. Nelle versioni precedenti la visualizzazione dell’icona non influisce sui conteggi.

## Risoluzione dei problemi

| Problema | Verifica |
| --- | --- |
| Integrazione assente dopo il download | Cartella corretta senza livelli aggiuntivi, riavvio eseguito; cerca in Aggiungi integrazione, non solo tra le schede |
| Scheda assente | Integrazione caricata, frontend aggiornato, URL e tipo Modulo JavaScript corretti in Risorse |
| **Nessun punto di ricarica accessibile. Configura Charge Tally o verifica le autorizzazioni.** | Deve esistere un punto e l’utente deve poterlo leggere; le sole identità non creano punti attivi |
| Nessuna registrazione automatica | Fonte di potenza, rilevamento configurato, interruttore attivo, soglie e durate effettivamente soddisfatte |
| **Avvia contabilizzazione manualmente** non disponibile | Fonti ed entità dell’identità disponibili, caricamento e riparazione completati |
| Cambiare identità non modifica la registrazione corrente | Il selettore prepara la prossima; usa **Cambia identità della registrazione** |
| Oggi mostra ancora registrazioni vecchie | Le date filtrano le statistiche, non **Registrazioni · tutte le date** |
| Solo subtotale noto o costo nativo assente | Verifica lacune, prezzi storici, valuta e qualità; non presumere una ricarica gratuita |
| Anteprima scaduta, registrazione cambiata o sovrapposizione | Aggiorna, riapri e rigenera l’anteprima; correggi gli orari sovrapposti, i controlli non si possono saltare |
| **Gli aiutanti del punto di ricarica richiedono una riparazione** | Apri la riparazione HA, scegli **Ripara gli aiutanti gestiti** e conferma; ricrea quelli dell’integrazione conservando lo storico |
| Valuta bloccata dopo la rimozione della configurazione | Restano dati archiviati: controlla **Gestisci dati archiviati** |
| Utente non amministratore senza accesso agli archivi o alle azioni | Verifica permessi HA di lettura/controllo; usa un amministratore per gli archivi. I filtri non concedono permessi |

> Segnaposto immagine 15: Avviso sugli aiutanti da riparare e conferma Ripara gli aiutanti gestiti.

Serve aiuto? [Apri una segnalazione](https://github.com/enecess/ha-charge-tally/issues) indicando versioni HA e Charge Tally, modalità di acquisizione e prezzo, passaggi e messaggi effettivi. Nascondi le informazioni private nelle immagini.

[Licenza MIT](LICENSE)

## Collegamenti identità NFC

Gli amministratori aprono **Impostazioni → Dispositivi e servizi → Charge Tally → Configura → Collegamenti identità NFC**. Registra prima un tag in HA, poi scegli tag, punto, dispositivi di scansione e identità. Puoi aggiungere più dispositivi o solo un’identità predefinita. Ogni coppia tag/punto ha un’automazione gestita; un tag condiviso può agire su più punti indipendenti.

Le associazioni dei dispositivi hanno precedenza. Gli altri usano l’identità predefinita facoltativa; senza di essa non accade nulla. Le registrazioni in corso e i candidati automatici bloccati mantengono l’identità. Rinominare un’identità conserva il collegamento. Un tag, dispositivo o punto eliminato, oppure un’identità disattivata, blocca l’intero collegamento fino alla correzione, senza ripiego su un’altra identità.

Nome e descrizione indicano che l’automazione è gestita da Charge Tally. Modifica i collegamenti nell’integrazione; usa HA per le tracce e la pausa. Il salvataggio mantiene la pausa. Rinominare l’ID dell’entità nativamente in HA può riattivare l’automazione: controlla quindi il suo interruttore. Le modifiche esterne richiedono un ripristino esplicito; le automazioni eliminate vanno ricreate. Dopo una disconnessione, completa l’operazione in sospeso per riutilizzare la stessa automazione.

Ripristino e ricreazione consentono di correggere le associazioni non valide prima della conferma. Sostituire modifiche esterne richiede una conferma esplicita. Un’eliminazione in sospeso può essere annullata finché l’automazione esiste, conservando la configurazione HA attuale.

Prima di rimuovere l’integrazione, elimina i collegamenti da questa pagina per ripulire le automazioni. Sono necessari i diritti amministratore e i componenti HA di automazione e configurazione. La funzione non scrive tag NFC e non controlla il caricatore.
