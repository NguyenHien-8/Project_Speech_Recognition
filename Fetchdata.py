from Installsubabase import supabase
response = (
    supabase.table("drinkdata")
    .select("ingredients")
    .execute()
)
print(response)