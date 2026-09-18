# Charge Tally

[English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [Polski](README.pl.md) · **Italiano**

Tieni traccia dell'energia e dei costi di ricarica in Home Assistant. Charge Tally utilizza i sensori di energia o potenza già disponibili per creare registrazioni di ricarica e ti consente di assegnare ogni registrazione a un veicolo, a un conducente o a un altro nome a tua scelta.

- Usa un prezzo fisso, un sensore di prezzo o prezzi diversi in base all'ora del giorno.
- Rileva automaticamente la ricarica oppure avvia e termina le registrazioni manualmente.
- Consulta l'energia e i costi di oggi, del mese e dell'anno per ogni identità.
- Aggiungi sessioni di ricarica passate e correggine i dettagli.
- Visualizza e gestisci tutto da una scheda della dashboard.

> Segnaposto per schermata: scheda della dashboard con stato della ricarica, selezione dell'identità e statistiche.

## Prima di iniziare

Sono necessari Home Assistant e almeno un sensore che misuri il circuito di ricarica. Charge Tally registra le ricariche; non accende né spegne il caricatore.

Richiede **Home Assistant 2025.3.4 o successivo**. Testato con le versioni 2025.3.4, 2025.12.4, 2026.3.4 e 2026.9.1.

| Sensori disponibili | Scelta durante la configurazione |
| --- | --- |
| Un totale cumulativo di energia in Wh, kWh o MWh | **Solo energia** |
| Potenza in W o kW | **Solo potenza** — Home Assistant calcola l'energia utilizzata |
| Entrambi | **Energia e potenza** — l'energia misura il consumo, la potenza rileva la ricarica |

Un totale cumulativo di energia è una lettura del contatore che normalmente aumenta, non la sola energia utilizzata nell'ultima ora. Il rilevamento automatico richiede un sensore di potenza.

## Installazione con HACS

1. Apri **HACS**, quindi il suo menu → **Repository personalizzati**.
2. Inserisci `https://github.com/enecess/ha-charge-tally` e scegli **Integrazione**.
3. Cerca **Charge Tally** in HACS e scaricalo.
4. Riavvia Home Assistant.
5. Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione** e cerca **Charge Tally**.

Per l'installazione manuale, copia la cartella `custom_components/charge_tally` del repository nella cartella `custom_components` di Home Assistant, quindi riavvia.

## Configura il primo punto di ricarica

Se il modulo del punto di ricarica non si apre automaticamente dopo la scelta della valuta, apri Charge Tally in **Impostazioni → Dispositivi e servizi** e scegli **Aggiungi punto di ricarica**.

1. **Scegli la valuta.** Tutti i punti di ricarica e i record condividono la stessa valuta. Puoi modificarla in Configura → Impostazioni del registro quando non restano punti (anche archiviati) né dati contabili. Le sole identità non la bloccano. Rimuovere un punto conserva la cronologia e il blocco. Eliminare tutti i punti e i relativi dati tramite Gestisci dati archiviati consente di modificare di nuovo la valuta. I prezzi dinamici devono usare la stessa valuta; gli importi non vengono convertiti automaticamente. Per ripristinare un registro conservato, scegli prima la sua valuta originale.
2. **Assegna un nome al punto di ricarica**, scegli quali sensori hai e selezionali.
3. Se hai un sensore di potenza, scegli se abilitare il **rilevamento automatico della ricarica**. Imposta i livelli di potenza e per quanto tempo devono essere mantenuti prima dell'inizio o della fine della ricarica. Il livello di fine deve essere inferiore a quello di avvio.
4. **Scegli il prezzo dell'elettricità** usando la tabella seguente.
5. Seleziona i contatori di energia giornalieri, mensili o annuali desiderati, quindi completa la configurazione.

| Opzione di prezzo | Cosa inserire |
| --- | --- |
| Prezzo fisso | Il prezzo per kWh |
| Prezzo dinamico | Un sensore di prezzo che utilizzi la stessa valuta di Charge Tally |
| Prezzo per fasce orarie | Inizio, fine e prezzo di ogni fascia, coprendo l'intera giornata |

I prezzi per fasce orarie si ripetono ogni giorno. Le fasce possono attraversare la mezzanotte; usa `24:00` per la fine della giornata. Sono supportati prezzi pari a zero e negativi.

> Segnaposto per schermata: selezione dei sensori e configurazione del prezzo dell'elettricità.

Per aggiungere un altro punto di ricarica o un'identità, apri **Charge Tally** in **Impostazioni → Dispositivi e servizi**. Da lì puoi anche modificare le impostazioni di un punto esistente. Termina la registrazione di ricarica in corso prima di modificare le impostazioni di misurazione o rilevamento.

## Aggiungi la scheda alla dashboard

Modifica la dashboard, seleziona **Aggiungi scheda** e cerca **Charge Tally**. L'editor consente di scegliere i punti di ricarica, le identità e le informazioni da visualizzare. La scheda segue la lingua e il tema di Home Assistant.

La scheda è normalmente disponibile in automatico. Se manca, aggiorna prima il browser. Se gestisci manualmente le risorse della dashboard, aggiungi `/charge_tally/charge-tally-card.js?v=0.1.2-3` come **Modulo JavaScript**, quindi aggiorna di nuovo.

## Usa le identità e le registrazioni di ricarica

Un'identità può rappresentare un'auto, un familiare o qualsiasi altra cosa di cui vuoi tenere traccia. Le identità sono condivise tra i punti di ricarica. **Unassigned** (non assegnata) è disponibile se non ne hai scelta una.

Scegli l'identità prima che inizi la ricarica. Una volta avviata, la registrazione mantiene quell'identità. Cambiare la selezione durante la ricarica prepara la registrazione **successiva**. Per correggere la registrazione attuale o una precedente, usa **Cambia identità della registrazione**.

Con il rilevamento automatico abilitato, una registrazione inizia e termina quando vengono soddisfatte le soglie di potenza e i tempi di attesa impostati. Le pause brevi possono rimanere nella stessa registrazione. Senza rilevamento, usa **Avvia registrazione** e **Termina registrazione** sulla scheda.

Per le tue automazioni, usa l'entità **Identità** del punto di ricarica per scegliere chi sta ricaricando. Ad esempio, un lettore RFID o un pulsante può cambiare questa selezione. Il selettore delle azioni delle automazioni offre anche azioni di Charge Tally per avviare o terminare una registrazione.

## Aggiungi o correggi ricariche passate

1. Seleziona **Aggiungi registrazione passata** sulla scheda oppure apri una registrazione terminata e scegli **Modifica registrazione**.
2. Scegli il punto di ricarica, l'identità e gli orari di inizio e fine.
3. Usa lo storico disponibile dei sensori oppure inserisci manualmente l'energia totale. Scegli come calcolare il costo oppure lascialo in sospeso se non lo conosci ancora.
4. Seleziona **Anteprima delle modifiche**, verifica il risultato, quindi **Salva anteprima**.

Lo storico dipende dai dati conservati da Home Assistant. Se mancano letture, puoi inserire il totale da un'altra fonte, ad esempio dalla registrazione del caricatore stesso. Due registrazioni dello stesso punto di ricarica non possono sovrapporsi.

Usa **Annulla registrazione** per escludere una registrazione errata dai totali. I dettagli precedenti rimangono disponibili per la consultazione.

> Segnaposto per schermata: una registrazione di ricarica passata e la sua anteprima prima del salvataggio.

## Comprendere i totali

- **Ricarica a cavallo della mezzanotte:** il consumo viene ripartito tra le date a cui appartiene. Lo stesso vale per i cambi di mese e di anno. Quando l'intervallo tra letture del contatore attraversa uno di questi confini, la ripartizione viene stimata in base al tempo trascorso.
- **Ricarica in corso:** i valori possono cambiare quando arrivano nuove letture o viene confermato l'orario di fine definitivo.
- **Costo in sospeso:** mancano alcuni prezzi. L'importo noto visualizzato rappresenta solo una parte del costo, non l'importo finale.
- **I totali dei contatori e delle registrazioni possono differire:** i contatori includono l'energia utilizzata al di fuori delle registrazioni di ricarica, ad esempio il consumo in standby. I totali delle identità includono solo le registrazioni a esse assegnate. Correggere una registrazione aggiorna le statistiche delle registrazioni, non lo storico del contatore.

## Gestisci dati archiviati

Apri **Charge Tally → Configura → Gestisci dati archiviati**. Sono elencati solo punti e identità le cui voci di configurazione sono state eliminate; disabilitarle non basta. Controlla il numero di record e revisioni, l’intervallo UTC, l’energia e il costo noto, quindi conferma esplicitamente l’eliminazione permanente.

Eliminare un punto rimuove i suoi record del registro, revisioni, campioni e cronologia prezzi. Prima di eliminare un’identità con record, trasferisci tutti i suoi record attuali, inclusi quelli annullati, a un’identità destinataria. Gli importi restano invariati e le vecchie revisioni mantengono il nome dell’identità originale per la verifica.

Queste operazioni non sono annullabili nell’interfaccia e riguardano solo il registro Charge Tally, non la cronologia nativa, le statistiche o i backup di Home Assistant. La valuta può essere modificata solo quando non restano punti di ricarica (anche archiviati) né dati contabili. Per ripristinarlo, scegli prima la valuta originale.

## Domande frequenti

**Perché non c'è una registrazione di ricarica?** Verifica che i sensori selezionati siano disponibili. Per il rilevamento automatico, verifica che sia abilitato e che la potenza rimanga sopra il livello di avvio per un tempo sufficiente. Altrimenti, avvia la registrazione manualmente.

**Perché il costo è in sospeso?** Controlla il sensore di prezzo e la sua valuta oppure apri la registrazione per inserire un totale noto. I dati mancanti non vengono considerati come costo zero.

**Perché Home Assistant chiede di riparare un punto di ricarica?** Uno dei contatori di energia creati per quel punto potrebbe essere stato rimosso o modificato. Apri l'avviso di riparazione e segui le istruzioni.

**Come posso aggiornare in sicurezza?** Crea un backup di Home Assistant, aggiorna Charge Tally tramite HACS e riavvia Home Assistant. La rimozione dell'integrazione non cancella le registrazioni di ricarica salvate.

Hai bisogno di aiuto? [Apri una segnalazione](https://github.com/enecess/ha-charge-tally/issues) indicando la versione di Home Assistant, la versione di Charge Tally e una descrizione del problema.

[Licenza MIT](LICENSE)
