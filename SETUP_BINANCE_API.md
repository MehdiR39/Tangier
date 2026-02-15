# Setup Binance API for Tangier Trading Strategy

## Quick Setup (3 Steps)

### Step 1: Get Your Binance API Keys

1. Go to **https://www.binance.com**
2. Log in to your account
3. Click your profile icon → **API Management**
4. Click **Create API** (or **Create New Key**)
5. Name it: `tangier-trading-strategy`
6. You'll get two keys:
   - **API Key** (public)
   - **Secret Key** (keep this secret!)

### Step 2: Create `.env` File

1. In the `tangier` folder, create a new file named `.env`
2. Copy this and paste it:

```
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_secret_key_here
```

3. Replace `your_api_key_here` and `your_secret_key_here` with your actual keys

### Step 3: Install Required Packages

```bash
pip install python-binance python-dotenv
```

## That's It! 🎉

Now when you run `python main.py`, the strategy will:

- ✅ Read your API keys from `.env`
- ✅ Fetch real data from Binance
- ✅ Run backtests on actual market data

## Example `.env` File

## ⚠️ Security Tips

1. **Never share your Secret Key** - it can be used to trade!
2. **Don't commit `.env` to Git** - add it to `.gitignore`:
   ```
   .env
   ```
3. **Use read-only API keys** if possible (Binance allows this)
4. **Add IP whitelist** on Binance for extra security

## Troubleshooting

### Error: "Binance API keys not found"

- Make sure `.env` file is in the `tangier` folder
- Check that you copied the keys correctly
- Restart your Python script

### Error: "Invalid API key"

- Double-check your API key and secret
- Make sure there are no extra spaces
- Regenerate the keys on Binance if needed

### Error: "python-binance not installed"

```bash
pip install python-binance python-dotenv
```

### Error: "Connection refused"

- Check your internet connection
- Verify Binance is not blocked in your region
- Try again in a few moments

## What Happens Without API Keys?

If you don't have `.env` or API keys:

- ✅ The strategy still works
- ✅ It uses **synthetic (fake) data** for testing
- ✅ Perfect for learning and testing the code
- ⚠️ Results won't reflect real market conditions

## Next Steps

1. ✅ Create `.env` file with your API keys
2. ✅ Install packages: `pip install python-binance python-dotenv`
3. ✅ Run: `python main.py`
4. ✅ Check the logs to see real data being fetched

Enjoy! 🚀
