"""Static reference tables of food sources by macronutrient.

Values are approximate, per 100 g of the stated form unless noted, and exist to
help users pick foods — not as precise nutrition data. Grouped for display:
two protein tables, two fat tables, one carbohydrate table, one fibre table.
"""

_5, _4, _3, _2 = "★★★★★", "★★★★", "★★★", "★★"

PROTEIN_VEGETARIAN = {
    "title": "Vegetarian protein sources",
    "subtitle": "per 100 g",
    "has_density": True,
    "headers": ["Source", "Form", "Calories", "Protein", "Density"],
    "rows": [
        ["Soya chunks", "Dry, uncooked", "~345 kcal", "~52 g", _5],
        ["Soybeans", "Dry, raw", "~430 kcal", "~36–40 g", _5],
        ["Peanuts", "Raw", "~560 kcal", "~25–26 g", _3],
        ["Moong dal", "Dry, uncooked", "~345 kcal", "~24 g", _4],
        ["Urad dal", "Dry, uncooked", "~340 kcal", "~24 g", _4],
        ["Masoor dal", "Dry, uncooked", "~350 kcal", "~24–25 g", _4],
        ["Toor / Arhar dal", "Dry, uncooked", "~335 kcal", "~22 g", _4],
        ["Almonds", "Raw", "~580 kcal", "~21 g", _2],
        ["Rajma", "Dry, uncooked", "~335 kcal", "~22–24 g", _4],
        ["Chickpeas / Kabuli chana", "Dry, uncooked", "~360 kcal", "~19–21 g", _3],
        ["Kala chana", "Dry, uncooked", "~360 kcal", "~20 g", _3],
        ["Paneer", "Fresh, as purchased", "~265–320 kcal", "~18–21 g", _4],
        ["Tofu", "Fresh, as purchased", "~75–145 kcal", "~8–17 g", _5],
        ["Greek yogurt / high-protein curd", "Ready to eat", "~60–100 kcal", "~8–10 g", _4],
        ["Regular curd / dahi", "Ready to eat", "~60–100 kcal", "~3–4 g", _2],
        ["Cow's milk", "Liquid", "~60–70 kcal", "~3–3.5 g", _2],
    ],
}

PROTEIN_NON_VEGETARIAN = {
    "title": "Non-vegetarian protein sources",
    "subtitle": "per 100 g raw edible weight",
    "has_density": True,
    "headers": ["Source", "Form", "Calories", "Protein", "Density"],
    "rows": [
        ["Chicken breast, skinless", "Raw", "~120 kcal", "~22–23 g", _5],
        ["Turkey breast", "Raw", "~110–120 kcal", "~23–24 g", _5],
        ["Tuna", "Raw", "~105–145 kcal", "~23–24 g", _5],
        ["Prawns / Shrimp", "Raw", "~85–100 kcal", "~20–24 g", _5],
        ["Rohu", "Raw", "~95–120 kcal", "~17–20 g", _4],
        ["Katla", "Raw", "~100–140 kcal", "~18–20 g", _4],
        ["Pomfret", "Raw", "~120–150 kcal", "~18–21 g", _4],
        ["Salmon", "Raw", "~200–210 kcal", "~20–22 g", _4],
        ["Mutton / Goat, lean", "Raw", "~140–200 kcal", "~20–22 g", _4],
        ["Whole egg", "Raw whole edible portion", "~140–150 kcal", "~12–13 g", _4],
        ["Egg white", "Raw", "~45–55 kcal", "~10–11 g", _5],
    ],
}

FAT_WHOLE_FOODS = {
    "title": "Healthy fat sources — nuts, seeds and whole foods",
    "subtitle": "per 100 g",
    "headers": ["Food", "Form", "Calories", "Fat", "Main fat characteristic"],
    "rows": [
        ["Walnuts (Akhrot)", "Raw", "~650 kcal", "~65 g", "Rich in PUFA; notable plant omega-3 ALA"],
        ["Flaxseeds (Alsi)", "Dry / raw", "~530 kcal", "~42 g", "Excellent plant source of ALA omega-3"],
        ["Chia seeds", "Dry / raw", "~485 kcal", "~31 g", "Rich in ALA omega-3 and fibre"],
        ["Almonds (Badam)", "Raw", "~575–580 kcal", "~49–50 g", "Predominantly unsaturated fat"],
        ["Peanuts (Moongfali)", "Raw", "~560–570 kcal", "~49 g", "Mostly unsaturated fat; affordable"],
        ["Sesame seeds (Til)", "Dry / raw", "~570 kcal", "~50 g", "Rich in unsaturated fats"],
        ["Sunflower seeds", "Dry / raw", "~580 kcal", "~51 g", "High in PUFA"],
        ["Pumpkin seeds", "Dry / raw kernels", "~560 kcal", "~49 g", "Unsaturated fats + protein"],
        ["Pistachios (Pista)", "Raw", "~560 kcal", "~45 g", "Mostly unsaturated fat"],
        ["Cashews (Kaju)", "Raw", "~550 kcal", "~44 g", "Mostly unsaturated fat"],
        ["Soybeans", "Dry / raw", "~430–450 kcal", "~19–20 g", "PUFA + protein"],
        ["Avocado", "Raw edible portion", "~160 kcal", "~15 g", "Predominantly monounsaturated fat"],
        ["Olives", "As eaten", "~115–145 kcal", "~11–15 g", "Predominantly monounsaturated fat"],
    ],
}

FAT_OILS = {
    "title": "Healthy fat sources — oils and concentrated fats",
    "subtitle": "per 100 g, as sold",
    "note": (
        "Almost every pure cooking oil is about 900 kcal per 100 g, so comparing "
        "oils by calories is largely useless. What matters is the fat profile and "
        "how the oil is used."
    ),
    "headers": ["Fat / Oil", "Calories", "Fat", "Main characteristic"],
    "rows": [
        ["Mustard oil", "~884–900 kcal", "~100 g", "MUFA + PUFA; contains ALA omega-3"],
        ["Groundnut / Peanut oil", "~884–900 kcal", "~100 g", "High in unsaturated fats"],
        ["Olive oil", "~884–900 kcal", "~100 g", "Rich in monounsaturated fat"],
        ["Rice bran oil", "~884–900 kcal", "~100 g", "Mixed unsaturated-fat profile"],
        ["Sesame oil", "~884–900 kcal", "~100 g", "Rich in unsaturated fats"],
        ["Soybean oil", "~884–900 kcal", "~100 g", "PUFA; includes some ALA"],
        ["Sunflower oil", "~884–900 kcal", "~100 g", "Generally rich in omega-6 PUFA"],
        ["Ghee", "~895–900 kcal", "~99–100 g", "High in saturated fat"],
        ["Butter", "~715–750 kcal", "~80–82 g", "High in saturated fat; contains water"],
        ["Coconut oil", "~890–900 kcal", "~100 g", "Predominantly saturated fat"],
    ],
}

CARB_GRAINS = {
    "title": "Healthy carbohydrate sources — grains and cereals",
    "subtitle": "per 100 g raw / dry / uncooked weight",
    "headers": ["Food", "Form", "Calories", "Carbs", "Protein", "Fibre", "Best use"],
    "rows": [
        ["Oats", "Dry, uncooked", "~380 kcal", "~66–68 g", "~13–17 g", "~10 g", "Breakfast, high-fibre carb"],
        ["Brown rice", "Raw, uncooked", "~360–370 kcal", "~76–78 g", "~7–8 g", "~3–4 g", "Main meal carb"],
        ["White rice", "Raw, uncooked", "~350–365 kcal", "~78–80 g", "~6–8 g", "~1–2 g", "Easy-to-digest training fuel"],
        ["Whole wheat atta", "Dry", "~340–365 kcal", "~70–75 g", "~11–13 g", "~10–12 g", "Roti / chapati"],
        ["Jowar (Sorghum)", "Raw grain / flour", "~330–350 kcal", "~67–73 g", "~9–11 g", "~6–10 g", "Roti, millet option"],
        ["Bajra (Pearl millet)", "Raw grain / flour", "~350–380 kcal", "~65–70 g", "~10–12 g", "~8–12 g", "Roti, energy-dense millet"],
        ["Ragi (Finger millet)", "Raw grain / flour", "~320–340 kcal", "~70–75 g", "~7–8 g", "Varies", "Roti, porridge"],
        ["Barley (Jau)", "Dry, uncooked", "~350 kcal", "~73–78 g", "~10–12 g", "High", "Porridge, grain dishes"],
        ["Quinoa", "Dry, uncooked", "~365–370 kcal", "~64 g", "~14 g", "~7 g", "Carb + useful protein"],
        ["Poha", "Dry", "~350–370 kcal", "~75–80 g", "~6–8 g", "Varies", "Convenient Indian breakfast"],
    ],
}

FIBRE_SOURCES = {
    "title": "Fibre sources",
    "subtitle": "approximate fibre content",
    "headers": ["Food", "State", "Fibre / 100 g", "Practical serving", "Fibre / serving"],
    "rows": [
        ["Chia seeds", "Dry", "~34 g", "15 g", "~5 g"],
        ["Flaxseeds / Alsi", "Dry", "~27 g", "15 g", "~4 g"],
        ["Rajma", "Dry / uncooked", "~15–25 g", "50 g dry", "~8–12 g"],
        ["Chickpeas / Chana", "Dry / uncooked", "~15–20 g", "50 g dry", "~7–10 g"],
        ["Lentils / Masoor", "Dry / uncooked", "~10–15 g", "50 g dry", "~5–8 g"],
        ["Oats", "Dry", "~10–11 g", "50 g", "~5 g"],
        ["Whole-wheat atta", "Dry", "~10–12 g", "100 g", "~10–12 g"],
        ["Barley / Jau", "Dry", "~15–17 g", "50 g", "~8 g"],
        ["Almonds", "Raw", "~12–13 g", "25 g", "~3 g"],
        ["Peanuts", "Raw", "~8–9 g", "30 g", "~2.5 g"],
        ["Green peas", "Fresh", "~5 g", "100 g", "~5 g"],
        ["Guava / Amrood", "Edible raw", "~5–6 g", "150 g", "~8 g"],
        ["Pear with skin", "Edible raw", "~3 g", "1 medium", "~5–6 g"],
        ["Apple with skin", "Edible raw", "~2–3 g", "1 medium", "~4–5 g"],
        ["Sweet potato", "Raw / cooked varies", "~3 g", "200 g", "~6 g"],
        ["Carrot", "Raw", "~3 g", "100 g", "~3 g"],
        ["Broccoli", "Raw / cooked varies", "~2.5–3.5 g", "150 g", "~4–5 g"],
    ],
}

# Grouped for the page: heading -> tables under it, in display order.
NUTRITION_TABLE_GROUPS = [
    ("Protein sources", [PROTEIN_VEGETARIAN, PROTEIN_NON_VEGETARIAN]),
    ("Fat sources", [FAT_WHOLE_FOODS, FAT_OILS]),
    ("Carbohydrate sources", [CARB_GRAINS]),
    ("Fibre sources", [FIBRE_SOURCES]),
]
