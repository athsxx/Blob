# Publish this profile (one-time)

This folder is a **standalone Git repo**: push it to GitHub as **`athsxx/athsxx`** (repository name **must** match your username) so the README shows on [github.com/athsxx](https://github.com/athsxx).

## 1. Create the repo on GitHub

- New repository → Owner **athsxx**, name **athsxx**, **Public**  
- **Do not** add a README, .gitignore, or license (this folder already has them).

## 2. Push from this machine

From the **`github-profile`** directory (first time only: `git init` if there is no `.git` yet):

```bash
cd /path/to/Blob/github-profile
git init
git add README.md SETUP.md .gitignore assets/
git commit -m "Add GitHub profile README"
git remote add origin https://github.com/athsxx/athsxx.git
git branch -M main
git push -u origin main
```

If `origin` already exists, use `git remote set-url origin https://github.com/athsxx/athsxx.git` instead.

## 3. Profile polish on GitHub

- **Settings → Public profile**: display name, short bio, website, location (optional).  
- **Profile**: **pin** up to six repositories.  
- Edit **`README.md`** here to add LinkedIn / email badges (see HTML comment at bottom of README).

## If stats cards are blank

[github-readme-stats](https://github.com/anuraghazra/github-readme-stats) and [streak-stats](https://github.com/DenverCoder1/github-readme-streak-stats) can rate-limit; refresh later or remove those `<img>` blocks temporarily.
