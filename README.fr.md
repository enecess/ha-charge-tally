# Charge Tally

[English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · **Français** · [Polski](README.pl.md) · [Italiano](README.it.md)

Comptabilisez l’énergie et le coût des recharges dans Home Assistant, par point de recharge et par identité, et vérifiez le calcul de chaque enregistrement. Charge Tally utilise vos capteurs d’énergie ou de puissance existants ; il assure la comptabilisation sans commander l’alimentation du chargeur.

- Un registre pour plusieurs points, avec des identités partagées pour les véhicules, conducteurs ou membres du foyer.
- Mesure à partir d’un compteur d’énergie cumulée, intégration de la puissance, ou mesure d’énergie associée à la détection par puissance.
- Prix fixes, dynamiques ou par plages horaires quotidiennes, y compris les prix nuls et négatifs.
- Détection automatique, ou démarrage et fin des enregistrements depuis la carte ou les automatisations Home Assistant.
- Suivi en direct, statistiques du jour, du mois, de l’année, de toute la période ou d’une période personnalisée, et graphiques regroupés par plage.
- Ajout d’enregistrements passés, modification des enregistrements terminés, changement d’identité, invalidation des erreurs, consultation des segments et de l’historique des modifications.
- Gestion des points et identités archivés, et suppression définitive des données devenues inutiles.

Deux accès principaux : **Paramètres → Appareils et services → Charge Tally** pour la configuration, et la carte **Charge Tally** du tableau de bord pour consulter et gérer les enregistrements. La carte réunit plusieurs zones sur une même page ; les détails et formulaires s’ouvrent dans des fenêtres de dialogue.

> Emplacement de capture 01 : carte complète avec les points, les statistiques et la liste des enregistrements.

## Comportement actuel de la carte et de la comptabilité

À l’ouverture, seules les commandes de charge sont dépliées. Les statistiques et les enregistrements sont repliés. Les mises à jour conservent les sections ouvertes et les commandes ; recharger la page rétablit les valeurs initiales. Le graphique et l’historique se chargent à l’ouverture de leur section.

Les graphiques regroupent Aujourd’hui par heure, Ce mois par jour, Cette année par mois et Total par année. Pour une plage personnalisée, l’écart entre les dates du calendrier local détermine le regroupement : jusqu’à 2 jours par heure, jusqu’à 90 jours par jour, jusqu’à 730 jours par mois, puis par année. Les intervalles suivent le fuseau du registre et les changements d’heure. Graphiques et totaux couvrent la même plage ; un coût inconnu reste inconnu.

Les segments de facturation des aperçus et détails fusionnent les intervalles adjacents dont la base de facturation, le tarif et la qualité sont identiques. Ils expliquent la facture, sans représenter chaque relevé. Les statistiques temporelles utilisent toujours les intervalles de mesure d’origine. L’historique des modifications conserve un instantané au démarrage, à la fin ou lors d’une modification explicite, y compris réaffectation et annulation. Les relevés courants modifient l’enregistrement sans nouvel instantané ; les numéros de révision peuvent donc comporter des sauts.

Supprimer la configuration d’un point conserve ses enregistrements inachevés. Dans **Configurer → Gérer les données archivées → Points de charge archivés**, sélectionnez le point supprimé, vérifiez le nombre d’enregistrements inachevés et les données concernées, puis confirmez explicitement la suppression définitive. Annuler préserve les données. Le nettoyage supprime les enregistrements, révisions, mesures et tarifs du point, sans supprimer les données Recorder de HA ni les sauvegardes.

Le format actuel du registre de développement a changé. Les anciens formats non pris en charge sont refusés sans migration ni suppression automatique. Il peut être nécessaire de recréer un registre de test jetable après sauvegarde ; la mise à jour n’effectue pas ce nettoyage.

## Sommaire

- [Avant de commencer](#avant-de-commencer)
- [Installer l’intégration](#installer-lintégration)
- [Première configuration](#première-configuration)
- [Identités et modifications de configuration](#identités-et-modifications-de-configuration)
- [Ajouter et configurer la carte](#ajouter-et-configurer-la-carte)
- [Les zones de la carte](#les-zones-de-la-carte)
- [Utiliser les enregistrements au quotidien](#utiliser-les-enregistrements-au-quotidien)
- [Ajouter ou modifier des enregistrements passés](#ajouter-ou-modifier-des-enregistrements-passés)
- [Comprendre les statistiques et la qualité des données](#comprendre-les-statistiques-et-la-qualité-des-données)
- [Entités natives et automatisations](#entités-natives-et-automatisations)
- [Gérer les archives et la devise](#gérer-les-archives-et-la-devise)
- [Mises à jour, sauvegardes et restauration](#mises-à-jour-sauvegardes-et-restauration)
- [Questions fréquentes](#questions-fréquentes)

## Avant de commencer

Il faut **Home Assistant 2025.3.4 ou ultérieur** et au moins un capteur mesurant le circuit de recharge. Utilisez un compte administrateur pour installer et configurer l’intégration. L’interface suit la langue de Home Assistant ; ce guide reprend les libellés affichés en français. L’emplacement des menus généraux peut varier selon la version de HA.

| Données disponibles | Choix du « Mode de saisie de l’énergie » | Utilisation |
| --- | --- | --- |
| Énergie cumulée en Wh, kWh ou MWh | **Énergie uniquement** | Comptabilisation à partir des relevés ; démarrage et fin depuis la carte ou une automatisation |
| Puissance en W ou kW | **Puissance uniquement (Integral natif)** | Création automatique d’une entrée auxiliaire Home Assistant pour calculer l’énergie ; détection automatique possible |
| Énergie cumulée et puissance | **Énergie et puissance** | Le capteur d’énergie mesure la consommation et la puissance sert à la détection ; les deux énergies ne sont pas additionnées |

L’énergie cumulée doit correspondre à un compteur généralement croissant, éventuellement remis à zéro, et non à une « consommation de la dernière heure ». Les capteurs doivent être correctement identifiés comme énergie ou puissance dans Home Assistant et fournir des valeurs numériques valides, positives ou nulles. Une même source ne peut pas être affectée à plusieurs points.

Pour un prix dynamique, préparez un capteur de prix utilisant la devise du registre. Pour reconstituer des enregistrements à partir de l’historique, vérifiez que Home Assistant enregistre les capteurs concernés et conserve encore les dates souhaitées.

## Installer l’intégration

### Méthode 1 : avec HACS

Si HACS n’est pas installé, suivez d’abord les [instructions officielles d’installation de HACS](https://hacs.dev/docs/use/download/download/).

**Ajouter à HACS en un clic :**

[![Ouvrir Charge Tally dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=enecess&repository=ha-charge-tally&category=integration)

Cliquez sur le bouton, saisissez ou confirmez l’adresse de votre Home Assistant, puis ajoutez ou ouvrez Charge Tally dans HACS. Reprenez à l’étape 3 ci-dessous pour télécharger, redémarrer et ajouter l’intégration, ou commencez à l’étape 1 pour ajouter le dépôt manuellement.

1. Ouvrez **HACS**, puis le menu en haut à droite et **Dépôts personnalisés**.
2. Ajoutez `https://github.com/enecess/ha-charge-tally` en choisissant le type **Intégration**.
3. Recherchez **Charge Tally**, ouvrez sa page et téléchargez la version souhaitée.
4. **Redémarrez Home Assistant** après le téléchargement.
5. Ouvrez **Paramètres → Appareils et services → Ajouter une intégration**, puis recherchez et sélectionnez **Charge Tally**.
6. Poursuivez avec la première configuration ci-dessous. Le téléchargement dans HACS ne crée pas encore le registre ni les points.

> Emplacement de capture 02 : dépôts personnalisés HACS, téléchargement Charge Tally et résultat dans « Ajouter une intégration ».

### Méthode 2 : installation manuelle

1. Téléchargez et décompressez ce dépôt, puis repérez le dossier `custom_components/charge_tally`.
2. Ouvrez le répertoire de configuration de Home Assistant, celui qui contient `configuration.yaml`.
3. Créez le dossier `custom_components` s’il n’existe pas, puis copiez-y tout le dossier `charge_tally`, avec ses sous-dossiers.
4. Vérifiez que le fichier final se trouve à `custom_components/charge_tally/manifest.json`, sans niveau supplémentaire correspondant au dépôt.
5. **Redémarrez Home Assistant**, puis ouvrez **Paramètres → Appareils et services → Ajouter une intégration → Charge Tally**.

La carte est fournie avec l’intégration ; aucune installation séparée de carte frontend dans HACS n’est nécessaire. Si l’intégration est introuvable, vérifiez la structure des dossiers et le redémarrage, puis actualisez la page et consultez les journaux de Home Assistant.

## Première configuration

### 1. Créer le registre

Dans **Registre Charge Tally**, renseignez la **Devise**, par exemple EUR, CNY ou USD. Une instance de Home Assistant utilise un seul registre Charge Tally ; tous les points et enregistrements partagent sa devise.

- La devise peut être modifiée tant qu’il ne reste aucun point, même archivé, ni aucune donnée comptable. Les identités seules ne la verrouillent pas.
- L’ajout d’un point verrouille la devise, même avant la première recharge.
- Supprimer uniquement la configuration conserve l’historique ; il faut nettoyer tous les points et leurs données pour pouvoir modifier à nouveau la devise.
- Aucune conversion monétaire automatique n’est effectuée. Lorsque vous ajoutez à nouveau une intégration supprimée, choisissez d’abord la devise d’origine du registre conservé.

> Emplacement de capture 03 : fenêtre « Registre Charge Tally » et explications sur la devise.

### 2. Ajouter un point de recharge

Après la création du registre, les versions de HA prenant en charge l’enchaînement automatique ouvrent la configuration du point. Sinon, ouvrez **Paramètres → Appareils et services → Charge Tally → Ajouter un point de recharge**.

Sur la page **Point de recharge**, saisissez un **Nom**, par exemple « Garage », puis choisissez le **Mode de saisie de l’énergie**. Un point représente un circuit de recharge mesuré indépendamment.

### 3. Choisir les sources de mesure

Dans **Sources de mesure**, développez **Mesure et détection** et renseignez les champs du mode choisi :

| Champ affiché | Que renseigner |
| --- | --- |
| **Capteur d’énergie cumulée** | Capteur mesurant l’énergie cumulée du circuit ; absent en mode « Puissance uniquement (Integral natif) » |
| **Capteur de puissance** | Capteur de puissance du circuit ; absent en mode « Énergie uniquement » |
| **Le compteur peut être réinitialisé** | Laissez activé si le compteur peut revenir à zéro ; une baisse est traitée comme une réinitialisation et rend l’intervalle concerné incomplet |
| **Intervalle maximal de répartition (secondes)** | 600 secondes par défaut ; les intervalles plus longs sont signalés comme des lacunes à vérifier |
| **Détection automatique de la recharge** | Disponible dans les modes avec puissance ; son activation ouvre ensuite les paramètres de détection |

### 4. Régler la détection automatique, si nécessaire

Après avoir activé **Détection automatique de la recharge**, renseignez **Détection automatique** :

- **Seuil de démarrage (W)** : une puissance supérieure ou égale à cette valeur lance la confirmation du début.
- **Durée de confirmation du démarrage (secondes)** : la condition doit persister avant la création de l’enregistrement ; 30 secondes par défaut.
- **Seuil d’arrêt (W)** : une puissance strictement inférieure lance la confirmation de la fin ; ce seuil doit être inférieur au seuil de démarrage.
- **Durée de confirmation de l’arrêt (secondes)** : la condition doit persister avant la fin de l’enregistrement ; 300 secondes par défaut.

Adaptez les seuils aux puissances réelles de veille et de recharge du chargeur. Après confirmation, l’heure retenue revient au début de la condition. Une pause plus courte que la durée de confirmation de l’arrêt reste dans le même enregistrement. Choisissez l’identité avant la montée en puissance : l’attribution est mémorisée dès le début de la confirmation.

La comptabilisation fonctionne aussi sans détection ; utilisez alors **Démarrer la comptabilisation manuellement** et **Terminer la comptabilisation**.

> Emplacement de capture 04 : section « Mesure et détection » de « Sources de mesure » et fenêtre « Détection automatique ».

### 5. Configurer les prix

Les choix de **Mode de tarification** et les fenêtres suivantes portent des noms légèrement différents :

| Choix | Fenêtre suivante | Informations à fournir |
| --- | --- | --- |
| **Fixe** | **Prix fixe** | **Prix par kWh**, dans la devise du registre |
| **Capteur dynamique** | **Prix dynamique** | **Capteur de prix**, et **Unité confirmée** si nécessaire |
| **Tarif journalier par plage horaire** | **Planning tarifaire journalier par plage horaire** | Plages tarifaires couvrant une journée |

Les prix fixes et par plage peuvent être nuls ou négatifs. Les prix dynamiques peuvent être exprimés dans la devise du registre par Wh, kWh ou MWh ; l’intégration harmonise l’unité d’énergie sans convertir la devise. **Unité confirmée** sert uniquement lorsque la source n’a pas d’unité. Elle ne permet pas de remplacer une devise ou une unité incorrecte déjà fournie par la source.

Pour définir le **Planning tarifaire journalier par plage horaire** :

1. Dans **Action**, choisissez **Ajouter une plage**.
2. Dans **Modifier la plage tarifaire**, renseignez **Heure de début**, **Heure de fin (24:00 = fin de journée)** et **Prix par kWh**.
3. Ajoutez les autres plages. Pour modifier ou supprimer une plage, sélectionnez la **Plage horaire**, puis **Modifier la plage** ou **Supprimer la plage**.
4. Une fois la journée entièrement couverte, choisissez **Terminer le planning**.

Utilisez le format `HH:MM`, par exemple `00:00–08:00`, `08:00–22:00`, `22:00–24:00`. Les plages passant par minuit, comme `22:00–06:00`, sont acceptées. Ni chevauchement, ni intervalle vide, ni heures de début et de fin identiques ne sont autorisés ; une journée entière s’écrit `00:00–24:00`. Le planning se répète chaque jour, sans distinction entre semaine et week-end.

> Emplacement de capture 05 : mode de tarification, confirmation d’unité dynamique, liste des plages et modification d’une plage.

### 6. Vérifier les périodes et le récapitulatif

Dans **Statistiques par période et récapitulatif**, vérifiez le nom du point, le mode de saisie et le mode de tarification. Choisissez ensuite les **Périodes des statistiques d’énergie** : **Journalières / Mensuelles / Annuelles**. Toutes sont sélectionnées par défaut ; vous pouvez aussi n’en sélectionner aucune.

Ces choix déterminent la création d’entrées auxiliaires natives de statistiques d’énergie supplémentaires. Ils ne conditionnent pas les statistiques des enregistrements de la carte ni celles des identités. Après validation, vérifiez que le point apparaît dans l’intégration, que les sources fonctionnent et qu’aucune réparation des entrées auxiliaires n’est demandée.

> Emplacement de capture 06 : « Statistiques par période et récapitulatif » et page de l’intégration après configuration.

## Identités et modifications de configuration

Dans **Paramètres → Appareils et services → Charge Tally**, utilisez l’accès correspondant :

| Accès | Utilisation |
| --- | --- |
| **Ajouter un point de recharge** | Ajouter un autre circuit mesuré indépendamment |
| **Configurer le point de recharge** | Modifier le nom, les capteurs, la détection, les prix et les périodes |
| **Ajouter une identité partagée** | Créer une identité pour un véhicule, une personne ou un autre usage |
| **Configurer l’identité** | Modifier le nom ou l’état **Activée** |
| **Configurer** sur l’intégration principale | Ouvrir **Paramètres du registre** et **Gérer les données archivées** |

La fenêtre **Identité partagée** contient seulement **Nom** et **Activée**. Les identités sont partagées entre les points ; leur nom ne doit pas dupliquer celui d’une autre identité configurée. L’identité intégrée **Unassigned** reçoit les enregistrements sans attribution ; ce nom anglais est conservé dans les listes de sélection.

Renommer une identité conserve l’attribution de son historique. Décocher **Activée** la retire des nouveaux choix, tout en conservant l’historique. Supprimer sa configuration conserve également l’historique et permet ensuite de la supprimer définitivement dans les archives. Désactiver et supprimer la configuration sont deux opérations distinctes.

Avant de modifier la mesure ou la détection, terminez l’enregistrement actif et attendez la fin des états de confirmation du début ou de la fin. Un changement de prix prend effet à partir de sa modification ; les montants déjà enregistrés ne sont pas recalculés au nouveau tarif. Terminez aussi tout enregistrement avant de supprimer un point : la suppression de sa configuration ne finalise pas automatiquement une recharge en cours.

> Emplacement de capture 07 : ajout ou configuration d’une identité partagée, et accès distincts à la configuration du point et du registre.

## Ajouter et configurer la carte

1. Configurez au moins un point, puis ouvrez le tableau de bord souhaité.
2. Passez en mode modification. Dans une disposition en sections, utilisez le bouton plus de la section ; dans les autres dispositions, utilisez **Ajouter une carte**.
3. Recherchez le type de carte **Charge Tally** et sélectionnez-le.
4. Réglez les options de l’éditeur visuel ci-dessous, enregistrez la carte et terminez la modification du tableau de bord.

| Champ de l’éditeur | Effet |
| --- | --- |
| **Titre** | Titre personnalisé ; vide, il affiche Charge Tally |
| **Point de recharge** | Point initialement sélectionné, ou **Toutes** |
| **Filtre d’identité** | Identité initialement sélectionnée, ou **Toutes** |
| **Afficher les enregistrements** | Afficher ou masquer la liste et son accès à l’ajout d’enregistrements passés |
| **Afficher le graphique** | Afficher ou masquer l’histogramme sans modifier les valeurs des statistiques |

Vous pouvez ajouter plusieurs cartes avec des points ou des identités différents. Ces filtres règlent l’affichage ; ils ne constituent pas des permissions de compte. Les utilisateurs n’accèdent qu’aux données autorisées par Home Assistant. La carte prend en charge le chinois simplifié, l’anglais, l’allemand, le français, le polonais et l’italien, et suit le thème.

> Emplacement de capture 08 : ajout de la carte Charge Tally et cinq options de l’éditeur visuel.

### La carte est absente de la liste

Vérifiez d’abord que l’intégration est chargée, puis actualisez le navigateur. Lorsque les ressources du tableau de bord sont gérées par l’interface, l’intégration enregistre normalement la carte automatiquement.

Si un enregistrement manuel reste nécessaire, ouvrez **Ressources** dans le menu de **Paramètres → Tableaux de bord**. Si cet accès n’apparaît pas, activez le **Mode avancé** dans votre profil. Ajoutez la ressource suivante, puis actualisez la page :

| Champ | Valeur |
| --- | --- |
| URL | `/charge_tally/charge-tally-card.js?v=0.1.2-5` |
| Type de ressource | **Module JavaScript** |

Si une ressource utilise déjà ce chemin, mettez-la à jour au lieu de la dupliquer. Si vous gérez les ressources en YAML, déclarez cette même adresse comme module dans votre configuration ; n’installez pas une seconde copie de la carte. Consultez la [documentation des tableaux de bord Home Assistant](https://www.home-assistant.io/dashboards/dashboards/) pour la gestion des ressources.

## Les zones de la carte

### Connexion et filtres

À côté du titre figurent **Connecté** ou **Déconnecté · en attente de données actualisées**. Après une déconnexion, utilisez **Réessayer** lorsque la connexion est rétablie ; un ancien affichage ne constitue pas un résultat de comptabilisation actualisé.

**Point de recharge** et **Filtre d’identité** s’appliquent aux statistiques et à la liste. Le point choisi détermine aussi les panneaux en direct affichés ; le filtre d’identité ne change pas l’identité sélectionnée sur un point. Les objets dont l’historique est conservé peuvent porter la mention **Archivé** : un point archivé permet de consulter son historique, sans panneau permettant de démarrer une recharge. Une identité désactivée peut aussi porter cette mention ; sa suppression définitive dépend des conditions de la gestion des archives dans la configuration.

### Panneaux des points en direct

Le panneau distingue la comptabilisation de la **Puissance** et de la **Détection**. **Aucune comptabilisation en cours**, **Comptabilisation manuelle en cours** et **Comptabilisation automatique en cours** décrivent le registre ; un enregistrement actif ne signifie pas que le chargeur consomme du courant. La détection indique séparément l’attente, la confirmation, la suspension pendant un enregistrement manuel, les données indisponibles ou l’attente d’une baisse de puissance.

Pendant la confirmation du début, **Identité fixée pour l’enregistrement automatique** indique l’identité mémorisée au début de la confirmation. **Identité du prochain enregistrement / enregistrement manuel** sert au prochain enregistrement automatique ou à un démarrage manuel immédiat, sans modifier l’identité fixée ni celle de l’enregistrement actif.

Chaque point actuel affiche son nom, son état, la **Puissance**, le **Prix actuel** et l’état de **Détection**. La puissance ou le prix peuvent être vides lorsqu’ils ne sont pas disponibles. **Détection** est un indicateur ; modifiez la détection dans la configuration du point ou avec l’interrupteur natif **Détection de la recharge**.

| Élément affiché | Signification |
| --- | --- |
| **Identité sélectionnée** | En l’absence d’enregistrement actif, choisir l’identité de la prochaine recharge |
| **Cet enregistrement** | Identité déjà attribuée à l’enregistrement actif |
| **Identité du prochain enregistrement** | Préparer l’identité suivante pendant une recharge, sans modifier l’attribution actuelle |
| **Comptabilisation en cours · Total actuel** | Énergie, coût, début, durée et indications de qualité de la recharge en cours |
| **Détails** | Ouvrir les détails de l’enregistrement actif |
| **Changer l’identité de l’enregistrement** | Corriger son attribution |
| **Démarrer la comptabilisation manuellement / Terminer la comptabilisation** | Démarrer ou terminer la comptabilisation à l’heure actuelle |

> Emplacement de capture 09 : panneau pendant une recharge, identité actuelle et suivante, coût provisoire et boutons d’action.

### Statistiques et graphique

Dans **Statistiques des enregistrements → Période des statistiques**, choisissez **Aujourd’hui / Ce mois-ci / Cette année / Toute la période / Période personnalisée**. Pour une période personnalisée, renseignez **Début** et **Fin (exclue)**, puis cliquez sur **Appliquer la période**. Pour consulter toute la journée du 1er septembre, choisissez le 1er septembre comme début et le 2 septembre comme fin.

Le récapitulatif affiche **Énergie**, **Coût**, le nombre **Actifs / terminés** et les indications de qualité. **Actualiser** récupère les derniers résultats. Le graphique est regroupé selon la plage choisie ; **Mesure du graphique** permet de choisir **Énergie** ou **Coût**. Développez **Détails** sous le graphique pour consulter les valeurs par intervalle dans un tableau.

> Emplacement de capture 10 : statistiques, dates personnalisées, mesure du graphique et tableau regroupé développé.

### Enregistrements · toutes les dates

Cette liste contient les enregistrements actifs et terminés, du début le plus récent au plus ancien, par pages de 25. Utilisez **Précédent / Suivant** pour changer de page. Chaque ligne affiche le point, l’identité, le début, l’état, l’énergie, le coût et les indications de qualité ; cliquez sur la ligne pour ouvrir les détails.

Seuls les filtres de point et d’identité s’appliquent : **les dates des statistiques ne limitent pas cette liste**. Même avec « Aujourd’hui », les anciens enregistrements restent visibles ici. **Ajouter un enregistrement passé** se trouve près du titre de la liste ; si elle est vide, **Aucun enregistrement** apparaît.

> Emplacement de capture 11 : liste « Enregistrements · toutes les dates », ajout d’un enregistrement passé, lignes et pagination.

## Utiliser les enregistrements au quotidien

### Démarrer et terminer manuellement

1. Choisissez l’identité puis **Démarrer la comptabilisation manuellement** ; pendant la confirmation du début, utilisez **Démarrer la comptabilisation maintenant**.
2. Vérifiez **Comptabilisation manuelle en cours** et les totaux actuels. Le démarrage manuel immédiat utilise l’identité actuellement sélectionnée et efface le candidat automatique.
3. Cliquez sur **Terminer la comptabilisation**, puis vérifiez l’enregistrement dans la liste.

Ces boutons enregistrent les horaires sans commander le chargeur. Un enregistrement démarré manuellement doit être terminé explicitement depuis la carte ou par une action d’automatisation. La détection automatique reste suspendue pendant cet enregistrement et ne le termine jamais, même à puissance nulle. Le démarrage exige une mesure d’énergie initiale valide ; un enregistrement existant peut être terminé même si les mesures deviennent indisponibles.

### Détecter automatiquement les recharges

Une fois configurée et activée, la détection peut suivre **Confirmation de la recharge → Suivi d’un enregistrement automatique → Confirmation de la fin → En attente de détection automatique**. Si la condition de puissance cesse pendant la confirmation, celle-ci est annulée. La confirmation automatique conserve l’identité fixée du candidat, même si la sélection change. **Terminer la comptabilisation manuellement** permet de terminer un enregistrement automatique plus tôt ; pendant la confirmation de fin, utilisez **Terminer la comptabilisation maintenant**.

Après une fin explicite, la détection attend normalement une puissance inférieure au seuil de fin. Elle peut reprendre immédiatement uniquement si la dernière mesure valide de faible puissance ne dépasse pas l’heure de la commande de fin, n’est pas plus ancienne que la durée de validité définie par **Intervalle maximal de répartition (secondes)** et n’a pas été invalidée par des données indisponibles ou un redémarrage. Une mesure élevée, absente, future ou trop ancienne ne lève pas le blocage. Après une puissance `unknown` ou indisponible, une nouvelle mesure valide sous le seuil est nécessaire. Le démarrage manuel reste possible pendant le blocage.

Avant de suspendre la détection avec **Détection de la recharge**, terminez les enregistrements actifs et les confirmations. Si les seuils manquent, ouvrez **Configurer le point de recharge**.

### Consulter les détails et les modifications

Les détails présentent l’attribution, l’énergie, le coût, les horaires, le fuseau de comptabilisation, l’**État**, la **Source**, la **Révision**, la note et les indications de qualité.

- **Segments de comptabilisation** : horaires, énergie, coût et **Qualité des données** de chaque segment, pour vérifier notamment les répartitions à minuit ou lors d’un changement de prix.
- **Historique des modifications** : développez cette section pour voir l’identité, l’état, les montants et la note de chaque révision. Il s’agit d’une trace d’audit, sans bouton de retour à une ancienne version.
- Un enregistrement actif permet de **Changer l’identité de l’enregistrement** ; seuls les enregistrements terminés proposent **Modifier l’enregistrement** et **Invalider l’enregistrement**.

> Emplacement de capture 12 : détails d’un enregistrement terminé, segments, historique des modifications développé et actions.

### Corriger l’identité

Ouvrez les détails et choisissez **Changer l’identité de l’enregistrement**, sélectionnez la bonne **Identité attribuée**, puis cliquez sur **Enregistrer l’aperçu**. C’est bien le nom actuel du bouton de validation de cette fenêtre ; aucune étape préalable « Aperçu des modifications » n’est nécessaire. L’attribution de l’ensemble de l’enregistrement change, sans recalcul de l’énergie ni du coût.

### Invalider un enregistrement erroné

Dans les détails d’un enregistrement terminé, choisissez **Invalider l’enregistrement**, vérifiez l’opération, puis cliquez sur **Confirmer l’invalidation**. Il disparaît des statistiques et de la liste ordinaire, mais le registre conserve l’original et les révisions. L’interface ne propose ni affichage des enregistrements invalidés ni bouton de restauration. L’invalidation n’est pas une suppression définitive.

## Ajouter ou modifier des enregistrements passés

**Ajouter un enregistrement passé** ouvre **Nouvel enregistrement passé**. Pour modifier un enregistrement existant, ouvrez un enregistrement terminé, puis **Modifier l’enregistrement**.

1. Vérifiez le **Fuseau horaire de comptabilisation**, puis choisissez le **Point de recharge** et l’**Identité attribuée**. Pour un nouvel enregistrement, utilisez un point actuel et une identité activée ; même si un point archivé apparaît dans la liste, il ne peut pas recevoir de nouvel enregistrement. En modification, le point est fixe et ne peut pas être remplacé.
2. Saisissez les dates et heures de **Début** et de **Fin (exclue)** ; la fin doit être postérieure au début.
3. Renseignez ou laissez vide l’énergie manuelle, puis choisissez la base de calcul du coût, selon le tableau ci-dessous.
4. Ajoutez si nécessaire une **Note**, limitée à 2000 caractères.
5. Cliquez sur **Aperçu des modifications**, puis vérifiez **Aperçu · vérifier avant d’enregistrer** : montant obtenu, segments, qualité des données et **Couverture des mesures**. En modification, les valeurs **Avant / Après** sont également affichées.
6. Vérifiez l’absence de chevauchement, puis cliquez sur **Enregistrer l’aperçu**. Toute modification du formulaire nécessite un nouvel aperçu ; **Fermer** ne sauvegarde pas.

| Champ ou choix | Comportement |
| --- | --- |
| À l’ajout : **Énergie manuelle (kWh, vide : utiliser l’historique)** | Vide, tente d’utiliser l’historique de mesure disponible ; sinon, utilise le total saisi |
| En modification : **Énergie manuelle (kWh, vide : conserver la base existante)** | Vide, conserve la base existante sans effacer une ancienne valeur manuelle |
| **Base de calcul du coût → Utiliser l’historique et les prix disponibles** | Choix par défaut à l’ajout ; dépend des données et prix effectivement conservés |
| **Base de calcul du coût → Conserver la base de calcul du coût** | Choix par défaut en modification, pour éviter qu’un simple changement de note provoque une nouvelle tarification |
| **Base de calcul du coût → Coût total manuel** | Active le champ **Coût total manuel** ; saisissez le montant total connu, éventuellement nul ou négatif |
| **Base de calcul du coût → En attente** | Laisse explicitement le coût inconnu ; il n’est pas considéré comme gratuit |

Les enregistrements d’un même point ne peuvent pas se chevaucher. Si l’aperçu signale un chevauchement, l’enregistrement est impossible. Si l’aperçu est périmé ou si l’enregistrement a changé, actualisez et générez un nouvel aperçu.

La reconstitution dépend des données encore conservées dans Home Assistant et dans le registre ; elle ne garantit pas la récupération de n’importe quelle date ancienne. Si les données manquent, utilisez par exemple le relevé du chargeur pour saisir l’énergie et le coût totaux manuels. Leur répartition temporelle entre les segments peut afficher **Remplacement manuel / Estimé**, qui indique la méthode de calcul.

Les dates et heures utilisent le fuseau affiché, et non celui du navigateur. Lorsqu’une heure locale se répète au changement d’heure, choisissez l’instant dans **Heure locale répétée : sélectionner l’instant UTC**. Une heure locale inexistante ne peut pas être validée.

> Emplacement de capture 13 : formulaires d’ajout et de modification, bases de calcul du coût, aperçu et couverture avant enregistrement.

## Comprendre les statistiques et la qualité des données

| Indication ou situation | Interprétation |
| --- | --- |
| **Provisoire / En attente de finalisation** | L’enregistrement ou ses limites de mesure ne sont pas encore entièrement déterminés ; de nouveaux relevés peuvent modifier le résultat |
| **sous-total connu · en attente** | Seule la part connue du coût est affichée ; la part inconnue n’est pas nulle |
| **Prix manquant / Prix inconnu** | Aucun prix valide pour la période ; vérifiez devise, unité, disponibilité et conservation de l’historique |
| **Énergie manquante / Interruption des observations** | Données insuffisantes ou relevés trop espacés ; vérifiez et complétez manuellement si nécessaire |
| **Compteur réinitialisé** | Une baisse du relevé rend l’intervalle concerné incomplet |
| **Remplacement manuel / Estimé** | Valeurs manuelles ou répartition temporelle ; il ne s’agit pas forcément de mesures réelles pour chaque instant |

L’énergie est répartie entre les jours, mois et années auxquels elle appartient ; une recharge passant minuit n’est pas entièrement affectée au jour de son début. Chaque enregistrement historique conserve son propre fuseau de comptabilisation. Le nombre d’enregistrements terminés est affecté selon leur heure de début : une recharge traversant la limite d’une période peut contribuer à son énergie sans augmenter son nombre d’enregistrements terminés.

La carte et les statistiques d’identité ne totalisent que les enregistrements de recharge. Les statistiques d’énergie natives peuvent aussi inclure la veille ou d’autres consommations hors enregistrement ; les totaux peuvent différer. Modifier un enregistrement actualise les statistiques du registre sans réécrire l’historique natif du compteur dans Home Assistant. Le graphique des coûts utilise les montants connus ; le nombre de décimales affichées ne modifie pas la précision conservée.

## Entités natives et automatisations

Outre la carte dédiée, vous pouvez utiliser les données de l’intégration dans les pages d’entités, d’autres cartes et les automatisations Home Assistant. Les exemples supposent un point nommé « Garage » et une identité « Voiture familiale » ; les noms réels suivent ceux que vous avez saisis.

| Entité visible | Utilisation |
| --- | --- |
| **Garage Énergie** | Énergie cumulée du point |
| **Garage État** | État actuel de recharge ou de disponibilité |
| **Garage Énergie de l’enregistrement / Garage Coût de l’enregistrement** | Enregistrement actif ; sans enregistrement actif, aucune valeur actuelle, et non la valeur de la dernière recharge |
| **Garage Identité** | Choix de l’identité suivante, utilisable avec une automatisation RFID, un bouton, etc. |
| **Garage Détection de la recharge** | Interrupteur de détection pour les modes avec puissance ; ne commande pas l’alimentation du chargeur |
| **Voiture familiale Énergie du jour / Coût du jour, Énergie du mois / Coût du mois, Énergie de l’année / Coût de l’année, Énergie totale / Coût total** | Statistiques des enregistrements de l’identité ; Unassigned possède également ces statistiques |

Quand un coût est incomplet, son entité native peut ne pas fournir de valeur complète, alors que la carte affiche encore le sous-total connu. Les entrées auxiliaires d’énergie journalières, mensuelles et annuelles choisies lors de la configuration du point ont un autre rôle que ces statistiques d’identité. Ne supprimez ni ne modifiez manuellement les entrées auxiliaires gérées par l’intégration.

Le sélecteur d’actions des automatisations propose **Charge Tally : Démarrer la comptabilisation / Terminer la comptabilisation / Réaffecter l’identité de l’enregistrement**. Le début et la fin utilisent l’heure actuelle du serveur ; ces actions ne permettent pas de saisir des horaires passés. Utilisez la carte pour les enregistrements historiques.

Ces actions demandent aussi un **ID de la requête** ; terminer ou réaffecter exige la **Révision attendue de l’enregistrement**. Ce ne sont donc pas de simples actions d’interrupteur où sélectionner un appareil suffit. Utilisez un nouvel identifiant pour chaque nouvelle opération et conservez l’identifiant et les paramètres lors d’une nouvelle tentative de la même opération. Pour changer seulement l’identité suivante, utilisez de préférence **Garage Identité**. Pour comptabiliser directement sans manipuler ces champs de validation, utilisez les boutons de la carte.

## Gérer les archives et la devise

### Configuration supprimée, invalidation et nettoyage définitif

| Opération | Résultat |
| --- | --- |
| Désactiver une identité | La retire des nouveaux choix, en conservant configuration et historique |
| Supprimer la configuration d’un point ou d’une identité | Conserve l’historique et rend l’objet candidat à la gestion des archives ; une désactivation ne suffit pas |
| Invalider un enregistrement | L’exclut de la liste ordinaire et des statistiques, en conservant les données d’audit |
| Opération définitive dans la gestion des archives | Supprime réellement les objets et données concernés du registre, sans annulation dans l’interface |

### Supprimer définitivement un point archivé

1. Sur l’intégration principale, ouvrez **Configurer → Gérer les données archivées → Points de charge archivés**.
2. Dans **Choisir un objet archivé**, sélectionnez un point dont la configuration a été supprimée.
3. Dans **Confirmer l’opération définitive**, vérifiez l’objet, l’opération, le nombre d’enregistrements incluant les invalidés, les révisions, la période UTC, l’énergie et le coût connu.
4. Cochez **Je comprends les conséquences et confirme la suppression définitive**, puis validez. **Opération d’archivage terminée** affiche le résultat et le nombre de suppressions.

Cette opération supprime les enregistrements du point, leurs révisions, les mesures et l’historique des prix du registre ; elle ne masque pas simplement un nom.

### Supprimer définitivement une identité archivée

Ouvrez **Configurer → Gérer les données archivées → Identités archivées**, puis sélectionnez l’objet. S’il possède des enregistrements, choisissez d’abord une **Identité destinataire** dans **Transférer les enregistrements** : une identité existante activée ou **Unassigned**. Sans enregistrement, vous passez directement à la confirmation.

Tous les enregistrements, y compris les invalidés, sont transférés avec leurs montants inchangés. L’identité source est supprimée ; les anciennes révisions conservent son nom d’origine pour l’audit. L’identité intégrée Unassigned ne peut pas être supprimée. Si l’objet est encore utilisé ou si les données changent pendant la confirmation, l’opération est bloquée : traitez les enregistrements actifs ou rouvrez l’aperçu.

Le nettoyage concerne uniquement le registre Charge Tally : **il n’efface ni l’historique natif de Home Assistant, ni les statistiques à long terme, ni les sauvegardes**. L’énergie et le coût connu de la confirmation incluent les enregistrements invalidés listés, pour décrire le périmètre traité ; ils ne sont pas directement comparables aux statistiques ordinaires qui les excluent.

> Emplacement de capture 14 : catégories d’archives, sélection d’objet, transfert d’identité et confirmation de l’opération définitive.

### Modifier la devise

Sur l’intégration principale, ouvrez **Configurer → Paramètres du registre**. Le formulaire de modification n’apparaît que lorsqu’il ne reste aucun point, même archivé, ni aucune donnée comptable. Sinon, **Devise du registre verrouillée** explique la situation. Les identités seules ne verrouillent pas la devise.

Pour repartir avec une autre devise, effectuez les sauvegardes nécessaires, supprimez la configuration des points inutilisés, nettoyez leurs données dans les archives, puis rouvrez les paramètres du registre. Ce processus permet de choisir une nouvelle devise après nettoyage ; il ne convertit pas les anciens montants.

## Mises à jour, sauvegardes et restauration

1. Avant la mise à jour, créez une sauvegarde incluant le répertoire de configuration Home Assistant.
2. Avec HACS, mettez à jour depuis HACS. Pour une installation manuelle, remplacez tout le dossier de l’intégration en conservant sa structure complète.
3. Redémarrez Home Assistant, puis actualisez le tableau de bord dans le navigateur ou l’application. Si vous gérez les ressources vous-même, vérifiez aussi la version de l’adresse indiquée plus haut.
4. Vérifiez l’état des points, les enregistrements et les statistiques. Si une réparation des entrées auxiliaires est demandée, suivez la procédure.

Le registre est conservé dans le répertoire de configuration Home Assistant ; lorsque Home Assistant crée une sauvegarde, l’intégration prépare une copie cohérente du registre. Supprimer l’intégration ou désinstaller ses fichiers ne vide pas volontairement le registre conservé ; lors du nouvel ajout, choisissez sa devise d’origine. Une restauration doit rétablir la configuration et le registre correspondants, sans mélanger des données de périodes différentes.

Les icônes de marque locales sont prises en charge à partir de **Home Assistant 2026.3**. Leur affichage sur une version plus ancienne n’affecte pas la comptabilisation.

## Questions fréquentes

| Problème | Vérifications |
| --- | --- |
| Charge Tally introuvable après téléchargement | Vérifiez l’installation de l’intégration, les dossiers sans imbrication supplémentaire et le redémarrage ; cherchez dans « Ajouter une intégration », pas uniquement dans les cartes |
| Carte introuvable | Chargez d’abord l’intégration, actualisez le frontend, puis vérifiez l’adresse dans « Ressources » et le type Module JavaScript |
| **Aucun point de recharge accessible. Configurer Charge Tally ou vérifier les autorisations.** | Vérifiez qu’au moins un point existe et que l’utilisateur peut le lire ; les identités seules ne créent pas de point en direct |
| Aucun enregistrement automatique | Vérifiez la source de puissance, la configuration complète de la détection, l’interrupteur activé et le respect réel des seuils et durées |
| « Démarrer la comptabilisation manuellement » indisponible | Vérifiez la source de mesure, la disponibilité de l’entité d’identité du point, et un éventuel chargement ou une réparation en cours |
| Le changement d’identité ne modifie pas la recharge actuelle | La liste prépare l’identité suivante ; utilisez « Changer l’identité de l’enregistrement » pour corriger une recharge existante |
| D’anciens enregistrements restent visibles avec « Aujourd’hui » | La période concerne les statistiques ; « Enregistrements · toutes les dates » n’est pas filtré par ces dates |
| Seulement un sous-total connu, ou aucune valeur du coût natif | Vérifiez les lacunes de mesure, l’historique des prix et la devise ; consultez la qualité dans les détails et ne considérez pas le coût comme nul |
| Aperçu périmé, enregistrement modifié ou chevauchement | Actualisez, rouvrez et générez un nouvel aperçu ; en cas de chevauchement, modifiez les horaires, sans contourner le contrôle |
| **Les entrées auxiliaires du point de recharge doivent être réparées** | Ouvrez la réparation HA, puis **Réparer les entrées auxiliaires gérées** et confirmez ; les entrées défectueuses appartenant à l’intégration sont recréées, avec conservation de l’historique |
| Devise verrouillée après suppression de la configuration | La suppression conserve les archives ; vérifiez dans « Gérer les données archivées » s’il reste des points ou des données comptables |
| Un compte ordinaire ne voit pas les archives ou ne peut pas agir | Vérifiez les permissions de lecture et de contrôle HA ; utilisez un compte administrateur pour gérer les archives. Les filtres de la carte n’accordent pas de permissions |

> Emplacement de capture 15 : notification de réparation des entrées auxiliaires et confirmation « Réparer les entrées auxiliaires gérées ».

Besoin d’aide ? [Ouvrez un ticket](https://github.com/enecess/ha-charge-tally/issues) avec les versions de Home Assistant et Charge Tally, les modes de mesure et de tarification, les étapes et le message exact. Masquez les informations privées sur les captures.

[Licence MIT](LICENSE)
