# Comptes (e-mail, Google, GitHub)

Un compte est **facultatif** : le widget marche très bien sans. Il identifie l'installation
(Réglages › Connexion, ou l'assistant du premier lancement). Il ne porte **que l'identité** : les
clés des fournisseurs IA et les conversations restent sur l'ordinateur de la personne.

## Pour les utilisateurs : rien à faire

Le projet de comptes (adresse et clé publique) est **intégré à l'application**. La connexion par
**code e-mail** marche d'emblée : tapez votre e-mail, puis le code à 6 chiffres reçu, une seule
fois ; le widget reste connecté d'une session à l'autre. Google et GitHub sont aussi proposés.

Le service de connexion est [Supabase Auth](https://supabase.com/docs/guides/auth). Toute la
connexion passe par le démon, jamais par le widget : le widget ne voit aucun jeton.

### Connexion par code e-mail

Le widget (assistant du premier lancement et Réglages › Connexion) demande l'e-mail, puis le code
à 6 chiffres reçu par e-mail. Côté démon, deux routes **publiques** (pas de jeton de widget à
présenter, puisque la personne n'est pas encore connectée) :

- `POST /auth/email/start` avec l'e-mail : le service envoie le code ;
- `POST /auth/email/verify` avec l'e-mail et le code : un code correct connecte le compte **et**
  crée le jeton du widget. Aucun code de bureau n'est nécessaire.

Le jeton du widget est gardé dans le Gestionnaire d'identifiants Windows : la personne reste
connectée d'une session à l'autre. Le code de couplage du bureau (*Réglages › Demander un code*)
existe toujours, mais seulement en **solution de repli** (hors ligne, ou sans e-mail).

#### Réglages Supabase requis pour les codes e-mail (projet auto-hébergé)

Dans le tableau de bord Supabase du projet :

1. **Authentication › Emails › SMTP Settings** : configurer un **SMTP personnalisé**. Sans lui,
   l'envoi par défaut de Supabase est très limité et ne convient pas à de vrais utilisateurs.
2. **Authentication › Emails › Templates** : les modèles **Confirm signup** *et*
   **Magic link or OTP** doivent **tous deux** contenir `{{ .Token }}` (le code). Un nouvel
   utilisateur reçoit « Confirm signup », un utilisateur existant « Magic Link » : si l'un des
   deux manque de `{{ .Token }}`, une partie des personnes ne recevra qu'un lien, sans code.
3. **Email OTP length** : 6 (le widget attend un code à 6 chiffres).

## Héberger ou forker : mettre en place son propre projet Supabase

À ne faire que si vous hébergez votre propre service de comptes (fork, auto-hébergement). Les utilisateurs de l'application officielle n'ont rien de tout ceci à faire.

1. **Créer un projet** sur supabase.com. Noter l'adresse du projet (`https://<ref>.supabase.co`,
   où `<ref>` est l'identifiant du projet) et la **clé publique** : Project Settings › API Keys ›
   *Publishable key* (`sb_publishable_…`). Les anciennes clés « anon » (`eyJ…`, *Legacy API
   keys*, retirées par Supabase en 2027) marchent aussi. Cette clé est faite pour être
   publique ; **ne donnez jamais une clé secrète** (`sb_secret_…` ou `service_role`) : la
   ligne de commande la refuse.
2. **Authentication › URL Configuration**
   - *Site URL* : `http://127.0.0.1:7341/auth/confirmed`
   - *Redirect URLs* : `http://127.0.0.1:7341/auth/callback`
   (remplacez 7341 si votre démon écoute sur un autre port).
3. **Authentication › Providers**
   - *Email* : activé (gardez « Confirm email » pour que l'adresse soit vérifiée).
   - *Google* : dans Google Cloud Console › APIs & Services › Credentials, créez un « OAuth
     client ID » de type *Web application* avec l'URI de redirection autorisée
     `https://<ref>.supabase.co/auth/v1/callback`, puis collez l'ID et le secret dans Supabase.
     Tant que l'écran de consentement est en mode « test », ajoutez les comptes autorisés.
   - *GitHub* : Settings › Developer settings › OAuth Apps › New OAuth App, avec
     `https://<ref>.supabase.co/auth/v1/callback` comme *Authorization callback URL*, puis
     collez le Client ID et un Client secret dans Supabase.
4. **Brancher le démon** :

   ```
   omniscient group auth set --url https://<ref>.supabase.co --anon-key <clé publique>
   omniscient group auth status
   ```

   Pas de redémarrage : le démon relit la configuration à chaque connexion. La configuration
   se fait **uniquement en ligne de commande**, jamais par l'API du démon.
5. Dans le widget : **Réglages › Compte** (ou l'étape « Compte » de l'assistant).

Les variables `OMNISCIENT_AUTH_URL` et `OMNISCIENT_AUTH_ANON_KEY` priment sur le fichier, qui prime lui-même sur la configuration intégrée.

## Comment ça marche, et ce qui est protégé

- **Google / GitHub** : OAuth avec PKCE. Le démon fabrique un secret à usage unique, envoie le
  navigateur chez Supabase avec son empreinte SHA-256, et le navigateur revient sur
  `http://127.0.0.1:<port>/auth/callback?code=…`. Un code n'est valable qu'avec **notre**
  secret : un lien piégé apporté par quelqu'un d'autre ne connecte personne. Une connexion
  dure 10 minutes et 3 essais.
- **E-mail** : code à usage unique envoyé par e-mail (voir plus haut) ; la connexion directe et la
  création de compte avec un lien de confirmation qui revient sur la même page restent possibles.
- **Jetons** : le jeton de renouvellement est gardé dans `<home>/.omniscient/auth_session.json`
  (0600), le jeton d'accès reste en mémoire. Aucune route ne renvoie un jeton ; l'état ne
  contient que l'e-mail, le nom et le fournisseur.
- **Adresse du service** : https vers un hôte public (ou la machine elle-même pour un essai
  local), revérifiée avant chaque appel ; pas de redirection suivie ; réponses plafonnées.
- **Mot de passe** : 8 à 128 caractères, 8 tentatives par 10 minutes ; jamais gardé, jamais
  affiché, jamais dans un message d'erreur.

## À savoir

- Le plan gratuit met le projet **en pause après une semaine sans activité** ; il se réveille
  d'un clic dans le tableau de bord Supabase.
- Les pages d'arrivée du navigateur sont fixes (aucun texte venant de l'URL n'y est repris).
- Pour héberger vous-même : Supabase est open source ; adresse et clé se règlent de la même
  façon (voir la section ci-dessus).
