import subprocess
import google.generativeai as genai
from typing import Optional, List, Dict, Tuple
import re
import json

class WingetInstallerGemini:
    def __init__(self, gemini_api_key: str):
        # Initialize Gemini API
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel('gemini-1.5-pro')
        self.search_results: List[Dict[str, str]] = []

    def parse_winget_output(self, output: str) -> List[Dict[str, str]]:
        """Parse the winget search output into structured data."""
        lines = output.strip().split('\n')
        if len(lines) < 3:
            return []

        data_lines = lines[2:]  # Skip header and separator
        parsed_results = []

        for line in data_lines:
            if not line.strip():
                continue

            parts = re.findall(r'(?:[^\s,"]|"(?:\\.|[^"])*")+', line.strip())
            if len(parts) >= 4:
                result = {
                    'name': parts[0].strip(),
                    'id': parts[1].strip(),
                    'version': parts[2].strip(),
                    'source': parts[-1].strip()
                }
                parsed_results.append(result)
        #print("parsed_results: ", parsed_results)
        return parsed_results

    async def analyze_packages_with_gemini(self, search_results: List[Dict[str, str]], user_input: str) -> Dict:
        """
        Use Gemini API to analyze packages and provide intelligent recommendations.
        """
        prompt = f"""
        You are a package selection expert. Analyze these software packages and recommend the best option for installing {user_input}.

        Package list:
        {json.dumps(search_results, indent=2)}

        Consider factors like:
        - Official/verified packages
        - Package popularity and maintenance
        - Version stability
        - Installation requirements

        Respond with a JSON object in this exact format:
        {{
            "recommended_package": "<package_id>",
            "reason": "<explanation>",
            "alternatives": [
                {{
                    "package_id": "<id>",
                    "use_case": "<specific use case>"
                }}
            ],
            "installation_notes": "<notes>"
        }}
        """

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text

            # Extract the JSON portion from the response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON object found in response")

            json_str = json_match.group(0)

            try:
                analysis = json.loads(json_str)

                required_fields = ['recommended_package', 'reason', 'alternatives', 'installation_notes']
                if not all(field in analysis for field in required_fields):
                    raise ValueError("Missing required fields in response")

                return analysis

            except json.JSONDecodeError as e:
                print(f"JSON parsing error: {e}")
                return {
                    "recommended_package": search_results[0]['id'],
                    "reason": "This is the most relevant package based on your search.",
                    "alternatives": [],
                    "installation_notes": "Standard installation process applies."
                }

        except Exception as e:
            print(f"Error analyzing packages with Gemini: {e}")
            return {
                "recommended_package": search_results[0]['id'],
                "reason": "This is the most relevant package based on your search.",
                "alternatives": [],
                "installation_notes": "Standard installation process applies."
            }

    def search_winget(self, user_input: str) -> Tuple[bool, List[Dict[str, str]]]:
        """Search for software in Winget repository."""
        try:
            result = subprocess.run(
                ["winget", "search", user_input],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )

            if result.returncode != 0:
                print(f"Error searching Winget repository:\n{result.stderr}")
                return False, []

            self.search_results = self.parse_winget_output(result.stdout)

            if not self.search_results:
                print(f"No packages found matching '{user_input}'")
                return False, []

            return True, self.search_results

        except Exception as e:
            print(f"Error executing Winget search: {e}")
            return False, []

    async def recommend_package(self, user_input: str, search_results: List[Dict[str, str]]) -> Optional[str]:
        """Get package recommendation from Gemini."""
        analysis = await self.analyze_packages_with_gemini(search_results, user_input)
        if not analysis:
            return search_results[0]['id'] if search_results else None
            
        print("\nPackage Analysis:")
        print(f"\nRecommended Package: {analysis['recommended_package']}")
        print(f"Reason: {analysis['reason']}")
        
        if analysis.get('alternatives'):
            print("\nAlternatives:")
            for alt in analysis['alternatives']:
                print(f"- {alt['package_id']}: {alt['use_case']}")
                
        if analysis.get('installation_notes'):
            print(f"\nInstallation Notes: {analysis['installation_notes']}")
            
        return analysis['recommended_package']

    async def install_application(self, user_input: str):
        """Main method to handle the software installation process."""
        try:
            print(f"\nSearching for '{user_input}' in Winget repository...")
            success, search_results = self.search_winget(user_input)

            if not success or not search_results:
                print("\nCouldn't find any packages to analyze.")
                return

            # Create a dictionary to store package data
            package_dict = {}
            for idx, pkg in enumerate(search_results, 1):
                package_dict[idx] = {
                    "name": pkg['name'],
                    "id": pkg['id'],
                    "version": pkg['version']
                }

            # Print package dictionary
            print("\nAvailable Packages:")
            for key, value in package_dict.items():
                print(f"{key}. {value['name']} ({value['id']}) - Version: {value['version']}")

            # Get intelligent recommendation from Gemini
            recommended_package = await self.recommend_package(user_input, search_results)

            if not recommended_package:
                print("\nCouldn't determine the best package to install.")
                return

            # Prompt user for choice
            while True:
                choice = input("\nEnter the number to select a package or 'exit' to quit: ").strip()

                if choice.lower() == 'exit':
                    print("\nInstallation process has been cancelled.")
                    return

                if choice.isdigit() and int(choice) in package_dict:
                    selected_package = package_dict[int(choice)]
                    print("Selected package:", selected_package)

                    # Check if the version contains letters (e.g., for pre-release versions)
                    if re.search(r'[a-zA-Z]', selected_package['version']):
                        package_id = selected_package['version']
                    else:
                        package_id = selected_package['id']

                    print(f"\nYou selected: {package_id})")

                    confirm = input(f"Install {package_id}? (y/n): ").lower()
                    if confirm != 'y':
                        print("Installation cancelled.")
                        return

                    print(f"\nInstalling {package_id}...")

                    # Execute installation process
                    command = ["winget", "install", package_id, "-e", "--source", "winget"]
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )

                    # Show real-time progress
                    for line in iter(process.stdout.readline, ""):
                        print(line.strip())

                    process.wait()  # Wait for the process to complete

                    if process.returncode == 0:
                        print(f"\nSuccessfully installed {selected_package['name']}")
                    else:
                        error_message = process.stderr.read().strip()

                        # Check for network-related errors or known issues
                        if "network" in error_message.lower() or "unable to connect" in error_message.lower() or "0x80072ee7" in error_message:
                            # Handle known error code (0x80072ee7) for network issues
                            print(f"\nNetwork error detected: {error_message}")
                            raise ConnectionError(f"Network issue detected during installation. Error details: {error_message}. Please check your internet connection and try again.")
                        else:
                            print(f"\nError during installation:\n{error_message}")

        except ConnectionError as e:
            print(f"Network Error: {e}")
        except Exception as e:
            print(f"Error in application installation process: {e}")





# Example usage
if __name__ == "__main__":
    import asyncio

    api_key = input("Enter your Gemini API key: ")

    installer = WingetInstallerGemini(api_key)

    async def main():
        while True:
            user_input = input("\nEnter the software you want to install (or 'exit' to quit): ")
            if user_input.lower() == 'exit':
                break
            await installer.install_application(user_input)

    asyncio.run(main())

