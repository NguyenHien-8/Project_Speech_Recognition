from spp import supabase
response = (
    supabase.table("drinkdata")
    .select("drink_name")
    .execute()
)
print(response)