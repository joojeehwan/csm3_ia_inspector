import os
import sys
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import ListSortOrder

load_dotenv()

endpoint = (
	os.getenv("AZURE_EXISTING_AIPROJECT_ENDPOINT")
	or os.getenv("AZURE_AGENT_ENDPOINT")
	or os.getenv("AZURE_OPENAI_ENDPOINT")
)
key = os.getenv("AZURE_AGENT_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
version = os.getenv("AZURE_AGENT_API_VERSION") or os.getenv("AZURE_OPENAI_API_VERSION")
agent_id = os.getenv("AZURE_EXISTING_AGENT_ID") or os.getenv("AZURE_AGENT_ID")

if not (endpoint and agent_id):
	print("Missing required env. Need AZURE_AGENT_ENDPOINT (or AZURE_OPENAI_ENDPOINT) and AZURE_AGENT_ID.")
	sys.exit(1)

def is_services_ai(url: str) -> bool:
	return "services.ai.azure.com" in (url or "")

if is_services_ai(endpoint):
	# Azure AI Agents via services.ai.azure.com uses AAD, not api-key
	print("Using Azure AI Agents (services.ai.azure.com) with DefaultAzureCredential…")
	try:
		cred = DefaultAzureCredential(exclude_interactive_browser_credential=False)
		project = AIProjectClient(credential=cred, endpoint=endpoint)
		print("Retrieving agent…", agent_id)
		agent = project.agents.get_agent(agent_id)
		print("Agent retrieved. Creating thread → message → run…")
		thread = project.agents.threads.create()
		project.agents.messages.create(thread_id=thread.id, role="user", content="ping")
		run = project.agents.runs.create_and_process(thread_id=thread.id, agent_id=agent.id)
		print("Run status:", run.status)
		if run.status == "failed":
			print("Run failed:", getattr(run, "last_error", None))
			sys.exit(1)
		msgs = project.agents.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING)
		for m in msgs:
			if getattr(m, "role", "") == "assistant" and getattr(m, "text_messages", None):
				print("assistant:", m.text_messages[-1].text.value)
		sys.exit(0)
	except Exception as e:
		print("Azure AI Agents error:", e)
		print("Hint: Ensure you're signed in (az login or VS Code Azure), and that endpoint is the exact Project URL. Keys are not used here.")
		sys.exit(1)
else:
	# Azure OpenAI Assistants via openai SDK
	if not (key and version):
		print("Missing AZURE_OPENAI_API_KEY or AZURE_OPENAI_API_VERSION for Azure OpenAI endpoint.")
		sys.exit(1)
	client = AzureOpenAI(azure_endpoint=endpoint, api_key=key, api_version=version)
	try:
		print("Retrieving agent…", agent_id)
		ass = client.beta.assistants.retrieve(assistant_id=agent_id)
		print("Agent name:", getattr(ass, "name", None))
		print("Creating thread and run…")
		thread = client.beta.threads.create()
		client.beta.threads.messages.create(thread_id=thread.id, role="user", content="ping")
		run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=agent_id)
		print("Run status:", run.status)
		sys.exit(0)
	except Exception as e:
		print("Azure OpenAI Assistants error:", e)
		print("Hint: endpoint must be https://<resource>.openai.azure.com, version must match Assistants, and agent must exist in that resource.")
		sys.exit(1)
