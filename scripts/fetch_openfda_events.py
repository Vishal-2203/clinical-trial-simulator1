import urllib.request
import json

DRUGS = {
    "Metformin (Diabetes)": "metformin",
    "Lisinopril (Hypertension)": "lisinopril",
    "Osimertinib (Cancer)": "osimertinib"
}

def fetch_top_reactions(drug_name):
    # Search for the medicinal product name and count the reaction terms (MedDRA Preferred Terms)
    url = f"https://api.fda.gov/drug/event.json?search=patient.drug.medicinalproduct:{drug_name}&count=patient.reaction.reactionmeddrapt.exact&limit=10"
    
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0'} # Basic headers to avoid blocker
        )
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get("results", [])
    except Exception as e:
        print(f"Error fetching data for {drug_name}: {e}")
        return []

def main():
    print("=" * 60)
    print("Fetching Top Adverse Events from openFDA API...")
    print("=" * 60)
    
    for label, api_name in DRUGS.items():
        print(f"\nTarget Drug: {label}")
        print("-" * 40)
        results = fetch_top_reactions(api_name)
        if not results:
            print("  No results returned or error occurred.")
            continue
            
        for idx, item in enumerate(results, 1):
            term = item.get("term", "Unknown").capitalize()
            count = item.get("count", 0)
            print(f"  {idx}. {term:<25} ({count:,} reports)")
            
    print("\n" + "=" * 60)
    print("Use these terms to populate safety / warning thresholds in the simulator.")
    print("=" * 60)

if __name__ == "__main__":
    main()
