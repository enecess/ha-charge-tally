# Charge Tally

[English](README.md) · [简体中文](README.zh-CN.md) · [Deutsch](README.de.md) · **Français** · [Polski](README.pl.md) · [Italiano](README.it.md)

Suivez l’énergie et le coût de vos recharges dans Home Assistant. Charge Tally utilise vos capteurs d’énergie ou de puissance existants pour créer des enregistrements de recharge, que vous pouvez attribuer à un véhicule, à une personne ou à tout autre nom de votre choix.

- Utilisez un prix fixe, un capteur de prix ou des tarifs selon l’heure de la journée.
- Détectez automatiquement les recharges ou démarrez et terminez les enregistrements vous-même.
- Consultez l’énergie et les coûts par identité pour aujourd’hui, ce mois et cette année.
- Ajoutez des recharges passées et corrigez leurs détails.
- Consultez et gérez le tout depuis une carte de tableau de bord.

> Emplacement prévu pour une capture d’écran : carte avec état de charge, choix de l’identité et statistiques.

## Avant de commencer

Vous avez besoin de Home Assistant et d’au moins un capteur mesurant le circuit de recharge. Charge Tally enregistre les recharges ; il n’allume ni n’éteint votre chargeur.

Nécessite **Home Assistant 2025.3.4 ou une version plus récente**. Testé avec les versions 2025.3.4, 2025.12.4, 2026.3.4 et 2026.9.1.

| Capteurs disponibles | Choix lors de la configuration |
| --- | --- |
| Un total d’énergie cumulé en Wh, kWh ou MWh | **Énergie uniquement** |
| La puissance en W ou kW | **Puissance uniquement** — Home Assistant calcule l’énergie consommée |
| Les deux | **Énergie et puissance** — l’énergie mesure la consommation, la puissance détecte la recharge |

Un total d’énergie cumulé est un relevé de compteur qui augmente normalement, et non la seule consommation de la dernière heure. La détection automatique nécessite un capteur de puissance.

## Installer avec HACS

1. Ouvrez **HACS**, puis son menu → **Dépôts personnalisés**.
2. Saisissez `https://github.com/enecess/ha-charge-tally` et choisissez **Intégration**.
3. Recherchez **Charge Tally** dans HACS et téléchargez-le.
4. Redémarrez Home Assistant.
5. Ouvrez **Paramètres → Appareils et services → Ajouter une intégration** et recherchez **Charge Tally**.

Pour une installation manuelle, copiez le dossier `custom_components/charge_tally` du dépôt dans le dossier `custom_components` de votre installation Home Assistant, puis redémarrez.

## Configurer votre premier point de charge

1. **Choisissez votre devise.** Tous les points de charge et enregistrements partagent une devise. Modifiez-la dans Configurer → Paramètres du registre si aucun point (même archivé) ni aucune donnée comptable ne subsiste. Les identités seules ne la verrouillent pas. Supprimer un point conserve son historique et le verrouillage. Nettoyer tous les points et leurs données via Gérer les données archivées permet de modifier à nouveau la devise. Les prix dynamiques doivent utiliser cette devise ; aucun montant n’est converti automatiquement. Pour restaurer un registre conservé, choisissez d’abord sa devise d’origine.
2. **Nommez le point de charge**, choisissez le type de capteurs dont vous disposez, puis sélectionnez-les.
3. Si vous avez un capteur de puissance, choisissez d’activer ou non la **détection automatique de recharge**. Réglez les seuils de puissance et leur durée avant le début ou la fin d’une recharge. Le seuil de fin doit être inférieur au seuil de début.
4. **Choisissez votre tarif d’électricité** à l’aide du tableau ci-dessous.
5. Sélectionnez les compteurs d’énergie quotidiens, mensuels ou annuels souhaités, puis terminez la configuration.

Si le formulaire du point de charge ne s’ouvre pas automatiquement, ouvrez **Charge Tally** dans **Paramètres → Appareils et services** et choisissez **Ajouter un point de recharge**.

| Type de tarif | Informations à saisir |
| --- | --- |
| Prix fixe | Votre prix par kWh |
| Prix dynamique | Un capteur de prix utilisant la même devise que Charge Tally |
| Tarif horaire | Le début, la fin et le prix de chaque plage, couvrant toute la journée |

Les tarifs horaires se répètent chaque jour. Une plage peut passer par minuit ; utilisez `24:00` pour la fin de la journée. Les prix nuls et négatifs sont acceptés.

> Emplacement prévu pour une capture d’écran : choix des capteurs et configuration du tarif d’électricité.

Pour ajouter un autre point de charge ou une identité, ouvrez **Charge Tally** dans **Paramètres → Appareils et services**. Vous pouvez aussi y modifier les réglages d’un point existant. Terminez son enregistrement en cours avant de changer les réglages de mesure ou de détection.

## Ajouter la carte au tableau de bord

Modifiez votre tableau de bord, choisissez **Ajouter une carte** et recherchez **Charge Tally**. L’éditeur permet de choisir les points de charge, les identités et les informations à afficher. La carte reprend la langue et le thème de Home Assistant.

La carte est normalement disponible automatiquement. Si elle manque, actualisez d’abord le navigateur. Si vous gérez vous-même les ressources du tableau de bord, ajoutez `/charge_tally/charge-tally-card.js?v=0.1.2-3` comme **Module JavaScript**, puis actualisez à nouveau.

## Utiliser les identités et les enregistrements

Une identité peut représenter une voiture, un membre de la famille ou tout autre élément à suivre séparément. Les identités sont communes à tous les points de charge. **Unassigned** est disponible si vous n’en avez pas choisi.

Choisissez l’identité avant de commencer la recharge. Un enregistrement commencé conserve cette identité. Changer la sélection pendant la recharge prépare l’enregistrement **suivant**. Pour corriger l’enregistrement actuel ou un ancien, utilisez **Changer l’identité de l’enregistrement**.

Lorsque la détection automatique est activée, un enregistrement démarre et se termine une fois les seuils de puissance et les délais atteints. De courtes pauses peuvent rester dans le même enregistrement. Sans détection, utilisez **Démarrer un enregistrement** et **Terminer l’enregistrement** sur la carte.

Dans vos automatisations, utilisez l’entité **Identité** du point de charge pour choisir qui recharge. Un lecteur RFID ou un bouton peut, par exemple, changer cette sélection. Le sélecteur d’actions des automatisations propose également des actions Charge Tally pour démarrer ou terminer un enregistrement.

## Ajouter ou corriger une recharge passée

1. Sur la carte, choisissez **Ajouter un enregistrement passé**, ou ouvrez un enregistrement terminé et choisissez **Modifier l’enregistrement**.
2. Sélectionnez le point de charge, l’identité ainsi que les heures de début et de fin.
3. Utilisez l’historique disponible des capteurs ou saisissez vous-même l’énergie totale. Choisissez le calcul du coût ou laissez-le en attente si vous ne le connaissez pas encore.
4. Choisissez **Aperçu des modifications**, vérifiez le résultat, puis **Enregistrer l’aperçu**.

L’historique disponible dépend des données conservées par Home Assistant. S’il manque des relevés, vous pouvez saisir le total depuis une autre source, comme l’historique de votre chargeur. Deux enregistrements d’un même point de charge ne peuvent pas se chevaucher dans le temps.

Utilisez **Invalider l’enregistrement** pour exclure un enregistrement incorrect des totaux. Ses anciens détails restent consultables.

> Emplacement prévu pour une capture d’écran : recharge passée et aperçu des modifications avant enregistrement.

## Comprendre les totaux

- **Recharge passant par minuit :** la consommation est répartie entre les dates concernées. Il en va de même pour les changements de mois et d’année. Si deux relevés de compteur encadrent cette limite, la répartition est estimée selon le temps écoulé.
- **Recharge en cours :** les chiffres peuvent évoluer à l’arrivée de nouveaux relevés ou à la confirmation de l’heure de fin définitive.
- **Coût en attente :** certains prix manquent. Le montant connu affiché ne représente qu’une partie du coût, pas le montant final.
- **Les totaux des compteurs et des enregistrements peuvent différer :** les compteurs incluent l’énergie consommée hors des enregistrements, par exemple en veille. Les totaux par identité incluent uniquement les enregistrements attribués à cette identité. Corriger un enregistrement actualise ses statistiques, pas l’historique du compteur.

## Gérer les données archivées

Ouvrez **Charge Tally → Configurer → Gérer les données archivées**. Seuls les points de charge et les identités dont les entrées de configuration ont été supprimées sont listés ; les désactiver ne suffit pas. Vérifiez les nombres d’enregistrements et de révisions, la période UTC, l’énergie et le coût connu, puis confirmez explicitement la suppression définitive.

Supprimer un point de charge efface ses enregistrements du registre, révisions, mesures et historique des prix. Avant de supprimer une identité ayant des enregistrements, transférez tous ses enregistrements actuels, y compris ceux annulés, vers une identité destinataire. Les montants restent inchangés ; les anciennes révisions conservent le nom d’identité d’origine pour l’audit.

Ces opérations sont irréversibles dans l’interface et concernent uniquement le registre Charge Tally, pas l’historique natif, les statistiques ou les sauvegardes Home Assistant. La devise peut être modifiée uniquement si aucun point de charge (même archivé) ni aucune donnée comptable ne subsiste. Lors d’une restauration, choisissez d’abord sa devise d’origine.

## Questions fréquentes

**Pourquoi aucun enregistrement de recharge n’apparaît-il ?** Vérifiez que les capteurs sélectionnés sont disponibles. Pour la détection automatique, vérifiez qu’elle est activée et que la puissance reste au-dessus du seuil de début assez longtemps. Sinon, démarrez l’enregistrement manuellement.

**Pourquoi le coût est-il en attente ?** Vérifiez le capteur de prix et sa devise, ou ouvrez l’enregistrement pour saisir un total connu. Les données manquantes ne sont pas considérées comme un coût nul.

**Pourquoi Home Assistant demande-t-il de réparer un point de charge ?** Un compteur d’énergie créé pour ce point a peut-être été supprimé ou modifié. Ouvrez l’avis de réparation et suivez ses instructions.

**Comment effectuer une mise à jour sereinement ?** Créez une sauvegarde Home Assistant, mettez Charge Tally à jour avec HACS, puis redémarrez Home Assistant. Supprimer l’intégration n’efface pas les enregistrements de recharge sauvegardés.

Besoin d’aide ? [Signalez un problème](https://github.com/enecess/ha-charge-tally/issues) en indiquant vos versions de Home Assistant et de Charge Tally, ainsi qu’une description du problème.

[Licence MIT](LICENSE)
