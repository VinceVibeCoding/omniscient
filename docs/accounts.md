# Comptes (Google, GitHub, e-mail + mot de passe)

Un compte est **facultatif** : le widget marche très bien sans. Il identifie l'installation
(Réglages › Compte, ou l'assistant du premier lancement). Il ne porte **que l'identité** : les
clés des fournisseurs IA et les conversations restent sur l'ordinateur de la personne.

Le service de connexion est [Supabase Auth](https://supabase.com/docs/guides/auth) : le plan
gratuit suffit pour démarrer, et Google, GitHub et e-mail + mot de passe y marchent sans
adaptateur. Toute la connexion passe par le démon, jamais par le widget : le widget ne voit
aucun jeton.

## Mettre en place (une fois, par le propriétaire du projet)

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

Les variables `OMNISCIENT_AUTH_URL` et `OMNISCIENT_AUTH_ANON_KEY` priment sur le fichier.

## Comment ça marche, et ce qui est protégé

- **Google / GitHub** : OAuth avec PKCE. Le démon fabrique un secret à usage unique, envoie le
  navigateur chez Supabase avec son empreinte SHA-256, et le navigateur revient sur
  `http://127.0.0.1:<port>/auth/callback?code=…`. Un code n'est valable qu'avec **notre**
  secret : un lien piégé apporté par quelqu'un d'autre ne connecte personne. Une connexion
  dure 10 minutes et 3 essais.
- **E-mail** : connexion directe, ou création de compte avec un lien de confirmation qui
  revient sur la même page.
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
  façon.
