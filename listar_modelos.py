from google import genai

client = genai.Client(api_key="AIzaSyCjpHs2Z4njvQlyRDfkX99D8BH202OFqDg")

print("Modelos disponibles:\n")
for modelo in client.models.list():
    print(modelo.name)
