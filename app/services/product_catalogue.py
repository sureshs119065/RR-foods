"""Product-page content for the 20 RR FOODS products. GENERATED from the Excel catalogue:

    python tools/build_catalogue_from_excel.py

Do not edit by hand; change the Excel and run the script again. Every text comes from the Excel. A field the Excel marks
"Not specified / Not captured" is None or empty and the product page shows nothing for it. The Excel column
"Editorial / Compliance Notes" is internal and is NOT stored here (see docs/INTERNAL-catalogue-review.md).
Ingredient-level nutrition text describes the grain or ingredient, never the finished product, and carries no health claim.
"""
import re
import unicodedata

PRODUCT_CATALOGUE = [{'number': 1,
  'sku': 'RR-MN-001',
  'name': 'Barnyard Millet Instant Noodles',
  'local_name': 'Kuthiraivali Noodles',
  'strapline': 'Traditional grain. Everyday goodness.',
  'description': 'Bring the goodness of Kuthiraivali into a familiar favourite. Made with barnyard millet, these '
                 'noodles offer a convenient way to explore traditional grains in everyday meals.',
  'ingredients': 'Kuthiraivali (Barnyard Millet) Flour, Whole Wheat Flour, Salt and Tastemaker.',
  'perfect_for': ['Quick breakfasts and evening snacks.',
                  'Busy weekdays and convenient family meals.',
                  'People interested in traditional millet-based foods.',
                  'Preparing flavourful vegetable noodle dishes.'],
  'serving': 'Enjoy hot with the seasoning mix. Add carrots, beans, cabbage, capsicum, sweet corn or spring onions '
             'for a colourful bowl.',
  'recipe_ideas': ['Vegetable Masala Noodles: Toss cooked noodles with sautéed carrots, beans, cabbage and capsicum.',
                   'Corn & Pepper Noodles: Add boiled sweet corn, crushed black pepper and spring onions.',
                   'Paneer Vegetable Noodles: Mix in sautéed paneer cubes and vegetables.'],
  'preparation': ['Boil 400 ml of water.',
                  'Add the noodles and cook for 10 minutes.',
                  'Stir in the seasoning mix.',
                  'Mix well and enjoy hot.'],
  'storage': 'Store in a cool, dry place. Once opened, transfer the contents to an airtight container and consume '
             'within 30 days.',
  'allergen': 'Contains wheat.',
  'net_weight': '180 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Fibre for digestive wellness: Barnyard millet has a dietary-fibre profile, supporting '
                        'normal digestion and bowel regularity.',
                        'Iron for healthy blood: Naturally occurring iron contributes to haemoglobin formation and '
                        'oxygen transport.',
                        'Plant-based protein: Protein contributes to the growth and maintenance of body tissues.',
                        'Mineral nourishment: Naturally provides minerals for everyday nutritional needs.'],
  'blend_details': [],
  'catalogue_mrp': '₹129',
  'catalogue_net_weight': '180 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 2,
  'sku': 'RR-MN-002',
  'name': 'Foxtail Millet Instant Noodles',
  'local_name': 'Thinai Noodles',
  'strapline': 'The goodness of Thinai in a familiar favourite.',
  'description': 'Make everyday meals more interesting with Thinai. Foxtail millet is valued for its protein and '
                 'fibre profile, making it a distinctive traditional grain to explore in a convenient noodle format.',
  'ingredients': 'Thinai (Foxtail Millet) Flour, Whole Wheat Flour and Salt.',
  'perfect_for': ['Quick breakfasts and evening cravings.',
                  'Convenient weekday meals.',
                  'People interested in exploring millet-based foods.',
                  'Preparing colourful vegetable noodle dishes.'],
  'serving': 'Enjoy hot with the seasoning mix. Add sweet corn, carrots, beans, capsicum, mushrooms or fresh herbs.',
  'recipe_ideas': ['Thinai Vegetable Noodles: Combine cooked noodles with sautéed seasonal vegetables.',
                   'Sweet Corn & Pepper Noodles: Add sweet corn, black pepper and spring onions.',
                   'Mushroom Masala Noodles: Toss prepared noodles with sautéed mushrooms, onions and seasoning.'],
  'preparation': ['Boil 400 ml of water.',
                  'Add the noodles and cook for 10 minutes.',
                  'Stir in the seasoning mix.',
                  'Mix well and enjoy hot.'],
  'storage': 'Store in a cool, dry place. Once opened, transfer the contents to an airtight container and consume '
             'within 30 days.',
  'allergen': 'Contains wheat.',
  'net_weight': '180 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Protein for body maintenance: Notable plant-protein content contributes to growth and '
                        'maintenance of body tissues.',
                        'Fibre for digestive wellness: Dietary fibre supports normal digestion and bowel regularity.',
                        'Magnesium for muscle function: Contributes to normal muscle and nerve function.',
                        'Phosphorus for bones and teeth: Contributes to maintenance of normal bones and teeth.'],
  'blend_details': [],
  'catalogue_mrp': '₹129',
  'catalogue_net_weight': '180 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 3,
  'sku': 'RR-MN-003',
  'name': 'Kodo Millet Instant Noodles',
  'local_name': 'Varagu Noodles',
  'strapline': 'Traditional grain. Versatile meals.',
  'description': 'Enjoy the familiar comfort of noodles with Varagu (Kodo Millet). A traditional grain brought into '
                 'a convenient format that makes everyday meals more interesting.',
  'ingredients': 'Varagu (Kodo Millet) Flour, Whole Wheat Flour, Salt and Tastemaker.',
  'perfect_for': ['Quick breakfasts and evening snacks.',
                  'Busy schedules and easy meals.',
                  'People looking to include traditional grains in their diets.',
                  'Preparing spicy Indian-style noodle dishes.'],
  'serving': 'Serve hot with the seasoning mix. Add fresh vegetables, mushrooms, sweet corn, green peas or paneer.',
  'recipe_ideas': ['Varagu Vegetable Noodles: Mix cooked noodles with sautéed carrots, beans and capsicum.',
                   'Spicy Indian Masala Noodles: Add onions, tomatoes, green chillies and coriander.',
                   'Mushroom & Corn Noodles: Combine sautéed mushrooms and sweet corn with prepared noodles.'],
  'preparation': ['Boil 400 ml of water.',
                  'Add the noodles and cook for 10 minutes.',
                  'Stir in the seasoning mix.',
                  'Mix well and enjoy hot.'],
  'storage': 'Store in a cool, dry place. Once opened, transfer the contents to an airtight container and consume '
             'within 30 days.',
  'allergen': 'Contains wheat.',
  'net_weight': '180 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Fibre for digestive wellness: Notable dietary-fibre profile supports normal bowel function.',
                        'Plant-based protein: Contributes to the growth and maintenance of body tissues.',
                        'Magnesium for normal body function: Contributes to normal muscle and nerve function.',
                        'Phosphorus for bone maintenance: Contributes to maintenance of normal bones and teeth.'],
  'blend_details': [],
  'catalogue_mrp': '₹129',
  'catalogue_net_weight': '180 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 4,
  'sku': 'RR-MN-004',
  'name': 'Little Millet Instant Noodles',
  'local_name': 'Saamai Noodles',
  'strapline': 'Small millet. Meaningful nutrition.',
  'description': 'Bring Saamai into your family’s everyday meals. Little millet offers a distinctive nutritional '
                 'profile, including dietary fibre and iron, in a convenient noodle format.',
  'ingredients': 'Saamai (Little Millet) Flour, Whole Wheat Flour, Salt and Tastemaker.',
  'perfect_for': ['Quick breakfasts and evening snacks.',
                  'Easy weekday meals.',
                  'People interested in traditional millet-based foods.',
                  'Preparing simple and flavourful noodle recipes.'],
  'serving': 'Enjoy with seasoning, fresh vegetables, sweet corn, mushrooms, green peas or paneer. Garnish with '
             'coriander or spring onions.',
  'recipe_ideas': ['Saamai Vegetable Noodles: Add sautéed carrots, beans, cabbage and capsicum.',
                   'Sweet Corn Masala Noodles: Combine prepared noodles with sweet corn and Indian spices.',
                   'Pepper & Mushroom Noodles: Add sautéed mushrooms, crushed pepper and spring onions.'],
  'preparation': ['Boil 400 ml of water.',
                  'Add the noodles and cook for 10 minutes.',
                  'Stir in the seasoning mix.',
                  'Mix well and enjoy hot.'],
  'storage': 'Store in a cool, dry place. Once opened, transfer the contents to an airtight container and consume '
             'within 30 days.',
  'allergen': 'Contains wheat.',
  'net_weight': '180 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Fibre for digestive wellness: Dietary fibre supports normal digestion and bowel regularity.',
                        'Iron for healthy blood: Naturally occurring iron contributes to haemoglobin formation and '
                        'oxygen transport.',
                        'Plant-based protein: Contributes to the growth and maintenance of body tissues.',
                        'Magnesium for everyday function: Contributes to normal muscle/nerve function and energy '
                        'metabolism.'],
  'blend_details': [],
  'catalogue_mrp': '₹129',
  'catalogue_net_weight': '180 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 5,
  'sku': 'RR-MN-005',
  'name': 'Multi Millet Instant Noodles',
  'local_name': 'Four Millet Noodles',
  'strapline': 'Four traditional millets. One convenient bowl.',
  'description': 'Why choose just one traditional grain? Enjoy a blend of Barnyard, Foxtail, Kodo and Little Millets '
                 'in one convenient noodle product. Four different grains come together to make everyday meals more '
                 'interesting.',
  'ingredients': 'Multi Millet Flour (Barnyard Millet, Foxtail Millet, Kodo Millet and Little Millet), Whole Wheat '
                 'Flour, Salt and Tastemaker.',
  'perfect_for': ['Family breakfasts and evening snacks.',
                  'Busy weekdays and convenient meals.',
                  'People exploring traditional millet varieties.'],
  'serving': 'Serve hot with seasoning, vegetables, sweet corn, mushrooms or paneer.',
  'recipe_ideas': ['Four Millet Vegetable Noodles: Combine prepared noodles with sautéed seasonal vegetables.',
                   'Mixed Millet Masala Noodles: Add onions, tomatoes, green chillies and coriander.'],
  'preparation': ['Boil 400 ml of water.',
                  'Add the noodles and cook for 10 minutes.',
                  'Stir in the seasoning mix.',
                  'Mix well and enjoy hot.'],
  'storage': 'Store in a cool, dry place. Once opened, transfer the contents to an airtight container and consume '
             'within 30 days.',
  'allergen': 'Contains wheat.',
  'net_weight': '180 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Barnyard Millet: Fibre supports digestive regularity; iron contributes to haemoglobin '
                        'formation.',
                        'Foxtail Millet: Plant protein supports tissue maintenance; magnesium contributes to normal '
                        'muscle/nerve function.',
                        'Kodo Millet: Dietary fibre supports digestive function; phosphorus contributes to '
                        'bone/teeth maintenance.',
                        'Little Millet: Dietary fibre supports bowel regularity; iron contributes to oxygen '
                        'transport.'],
  'blend_details': [],
  'catalogue_mrp': '₹129',
  'catalogue_net_weight': '180 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 6,
  'sku': 'RR-MV-001',
  'name': 'Barnyard Millet Vermicelli',
  'local_name': 'Kuthiraivali Semiya',
  'strapline': 'Traditional grain. Nourishing everyday meals.',
  'description': 'Bring Kuthiraivali into your kitchen with a versatile vermicelli that works beautifully in '
                 'familiar breakfast and dinner recipes. Enjoy the traditional grain in a convenient form your '
                 'family can prepare in many ways.',
  'ingredients': 'Kuthiraivali (Barnyard Millet) Flour, Whole Wheat Flour.',
  'perfect_for': ['Traditional South Indian breakfasts.',
                  'Quick and satisfying evening meals.',
                  'Family-friendly vegetable recipes.',
                  'People interested in bringing traditional millets into their daily menu.'],
  'serving': 'Enjoy as vegetable semiya upma, lemon semiya, coconut semiya or a savoury breakfast with seasonal '
             'vegetables.',
  'recipe_ideas': ['Kuthiraivali Vegetable Upma: Prepare with onions, carrots, beans, peas, curry leaves and green '
                   'chillies.',
                   'Lemon Semiya: Toss with mustard seeds, curry leaves, peanuts, turmeric and fresh lemon juice.',
                   'Coconut Semiya: Mix with grated coconut and a light mustard-seed tempering.'],
  'preparation': ['First, roast the vermicelli lightly.',
                  'Then, sauté mustard seeds, curry leaves, onions and vegetables.',
                  'Add water and bring it to a boil.',
                  'Finally, add the vermicelli and cook until soft.',
                  'Serve hot!'],
  'storage': 'Store in a cool, dry and hygienic place, away from direct sunlight.',
  'allergen': 'Contains wheat.',
  'net_weight': '200 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Fibre for digestive wellness: Dietary fibre supports normal digestion and bowel regularity.',
                        'Iron for healthy blood: Naturally occurring iron contributes to haemoglobin formation and '
                        'oxygen transport.',
                        'Plant-based protein: Contributes to the growth and maintenance of body tissues.',
                        'Naturally occurring minerals: Provides a variety of minerals for everyday nutrition.'],
  'blend_details': [],
  'catalogue_mrp': '₹99',
  'catalogue_net_weight': '200 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 7,
  'sku': 'RR-MV-002',
  'name': 'Foxtail Millet Vermicelli',
  'local_name': 'Thinai Semiya',
  'strapline': 'The goodness of Thinai in every meal.',
  'description': 'Make everyday meals more interesting with Thinai. Foxtail millet is recognised for its protein and '
                 'dietary-fibre profile, making it a distinctive traditional grain to explore in familiar semiya '
                 'recipes.',
  'ingredients': 'Thinai (Foxtail Millet) Flour, Whole Wheat Flour.',
  'perfect_for': ['Breakfast and evening tiffin.',
                  'Quick weekday cooking.',
                  'Vegetable-based family meals.',
                  'Customers looking to add more traditional grain variety to their diet.'],
  'serving': 'Serve as vegetable semiya, lemon semiya, coconut semiya or a lightly spiced breakfast with seasonal '
             'vegetables.',
  'recipe_ideas': ['Thinai Vegetable Semiya: Add carrots, beans, peas, onions and curry leaves for a colourful upma.',
                   'Lemon Thinai Semiya: Combine cooked semiya with lemon juice, roasted peanuts, green chillies and '
                   'curry leaves.',
                   'Thinai Curd Semiya: Mix cooled semiya with fresh curd, grated carrots and tempering.'],
  'preparation': ['First, roast the vermicelli lightly.',
                  'Then, sauté mustard seeds, curry leaves, onions and vegetables.',
                  'Add water and bring it to a boil.',
                  'Finally, add the vermicelli and cook until soft.',
                  'Serve hot!'],
  'storage': 'Store in a cool, dry and hygienic place, away from direct sunlight.',
  'allergen': 'Contains wheat.',
  'net_weight': '200 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Plant protein for body maintenance: Notable plant-protein content contributes to growth and '
                        'maintenance of body tissues.',
                        'Fibre for digestive wellness: Dietary fibre supports normal digestion and bowel regularity.',
                        'Magnesium for normal muscle function: Contributes to normal muscle and nerve function.',
                        'Phosphorus for bones and teeth: Contributes to maintenance of normal bones and teeth.'],
  'blend_details': [],
  'catalogue_mrp': '₹99',
  'catalogue_net_weight': '200 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 8,
  'sku': 'RR-MV-003',
  'name': 'Kodo Millet Vermicelli',
  'local_name': 'Varagu Semiya',
  'strapline': 'Traditional grain. Versatile meals.',
  'description': 'Bring Varagu into everyday cooking with a vermicelli that adapts easily to traditional and modern '
                 'recipes. A simple way to explore the distinctive nutritional profile of kodo millet.',
  'ingredients': 'Varagu (Kodo Millet) Flour, Whole Wheat Flour.',
  'perfect_for': ['Everyday South Indian breakfasts.',
                  'Quick family meals.',
                  'Light evening tiffin.',
                  'People interested in traditional millet-based cooking.'],
  'serving': 'Prepare as vegetable upma, lemon semiya or coconut semiya. Add seasonal vegetables, peanuts, curry '
             'leaves and fresh herbs.',
  'recipe_ideas': ['Varagu Vegetable Upma: Cook with carrots, beans, peas, onions, mustard seeds and curry leaves.',
                   'Spiced Varagu Semiya: Add tomatoes, green chillies, turmeric and coriander.',
                   'Coconut & Peanut Semiya: Toss cooked semiya with grated coconut and roasted peanuts.'],
  'preparation': ['First, roast the vermicelli lightly.',
                  'Then, sauté mustard seeds, curry leaves, onions and vegetables.',
                  'Add water and bring it to a boil.',
                  'Finally, add the vermicelli and cook until soft.',
                  'Serve hot!'],
  'storage': 'Store in a cool, dry and hygienic place, away from direct sunlight.',
  'allergen': 'Contains wheat.',
  'net_weight': '200 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Fibre for digestive wellness: Notable dietary-fibre profile supports normal bowel function.',
                        'Plant-based protein: Contributes to the growth and maintenance of body tissues.',
                        'Magnesium for everyday body functions: Contributes to normal muscle and nerve function.',
                        'Phosphorus for bone maintenance: Contributes to maintenance of normal bones and teeth.'],
  'blend_details': [],
  'catalogue_mrp': '₹99',
  'catalogue_net_weight': '200 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 9,
  'sku': 'RR-MV-004',
  'name': 'Little Millet Vermicelli',
  'local_name': 'Saamai Semiya',
  'strapline': 'Small millet. Meaningful everyday nutrition.',
  'description': 'A small millet with a distinctive nutritional profile, brought into a familiar and easy-to-prepare '
                 'food. Enjoy Saamai in traditional semiya recipes and give your everyday menu more variety.',
  'ingredients': 'Saamai (Little Millet) Flour, Whole Wheat Flour.',
  'perfect_for': ['Daily breakfast and evening tiffin.',
                  'Quick vegetable-based meals.',
                  'Traditional South Indian recipes.',
                  'Families looking to explore different millet varieties.'],
  'serving': 'Enjoy with vegetables, coconut, lemon, peanuts or curd. Can be used for both savoury and mildly sweet '
             'semiya dishes.',
  'recipe_ideas': ['Saamai Vegetable Semiya: Prepare with seasonal vegetables, onions, curry leaves and green '
                   'chillies.',
                   'Lemon Saamai Semiya: Add lemon juice, peanuts, mustard seeds, turmeric and curry leaves.',
                   'Saamai Coconut Semiya: Combine cooked semiya with grated coconut and a simple tempering.'],
  'preparation': ['First, roast the vermicelli lightly.',
                  'Then, sauté mustard seeds, curry leaves, onions and vegetables.',
                  'Add water and bring it to a boil.',
                  'Finally, add the vermicelli and cook until soft.',
                  'Serve hot!'],
  'storage': 'Store in a cool, dry and hygienic place, away from direct sunlight.',
  'allergen': 'Contains wheat.',
  'net_weight': '200 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Fibre for digestive wellness: Naturally provides dietary fibre that supports normal '
                        'digestion and bowel regularity.',
                        'Iron for healthy blood: Naturally occurring iron contributes to haemoglobin formation and '
                        'oxygen transport.',
                        'Plant-based protein: Contributes to the growth and maintenance of body tissues.',
                        'Mineral nourishment: Contributes naturally occurring minerals such as magnesium and '
                        'phosphorus.'],
  'blend_details': [],
  'catalogue_mrp': '₹99',
  'catalogue_net_weight': '200 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 10,
  'sku': 'RR-MV-005',
  'name': 'Mapillai Samba Rice Vermicelli',
  'local_name': 'Mapillai Samba Semiya',
  'strapline': 'The heritage of traditional Tamil rice in every meal.',
  'description': 'Discover the character of Mapillai Samba, a traditional red rice variety from Tamil Nadu. Its '
                 'distinctive grain colour and naturally occurring plant compounds make it an interesting choice for '
                 'bringing traditional rice varieties into everyday meals.',
  'ingredients': 'Mapillai Samba (Bridegroom Rice) Flour, Whole Wheat Flour.',
  'perfect_for': ['Traditional South Indian breakfasts.',
                  'People interested in heritage rice varieties.',
                  'Everyday family meals.',
                  'Preparing regional sevai and semiya recipes.'],
  'serving': 'Enjoy as lemon sevai, coconut sevai or vegetable semiya. Pair with sambar, chutney or a traditional '
             'vegetable side dish.',
  'recipe_ideas': ['Mapillai Samba Lemon Sevai: Toss prepared vermicelli with lemon juice, peanuts, mustard seeds, '
                   'curry leaves and turmeric.',
                   'Mapillai Samba Coconut Sevai: Combine cooked vermicelli with fresh grated coconut and light '
                   'tempering.',
                   'Mapillai Samba Vegetable Semiya: Add carrots, beans, peas and onions.'],
  'preparation': ['First, roast the vermicelli lightly.',
                  'Then, sauté mustard seeds, curry leaves, onions and vegetables.',
                  'Add water and bring it to a boil.',
                  'Finally, add the vermicelli and cook until soft.',
                  'Serve hot!'],
  'storage': 'Store in a cool, dry and hygienic place, away from direct sunlight.',
  'allergen': 'Contains wheat.',
  'net_weight': '200 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Naturally occurring plant compounds: Research on Mapillai Samba grain has identified '
                        'phenolic compounds and anthocyanins.',
                        'Antioxidant activity in grain research: Studies have reported antioxidant activity in '
                        'analysed grain samples.',
                        'Traditional rice variety: Offers a distinctive alternative to vermicelli made with familiar '
                        'rice varieties.'],
  'blend_details': [],
  'catalogue_mrp': '₹99',
  'catalogue_net_weight': '200 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 11,
  'sku': 'RR-MV-006',
  'name': 'Multi Millet Vermicelli',
  'local_name': 'Multi Millet Semiya',
  'strapline': 'Five traditional grains. One versatile semiya.',
  'description': 'Why settle for one grain? Bring together Barnyard, Foxtail, Kodo and Little Millets with Mapillai '
                 'Samba rice in one versatile vermicelli. A thoughtful combination of traditional grains for '
                 'everyday cooking.',
  'ingredients': 'Multi Millet and Rice Flour (Barnyard Millet, Foxtail Millet, Kodo Millet, Little Millet and '
                 'Mapillai Samba Rice), Whole Wheat Flour.',
  'perfect_for': ['Everyday family breakfasts and traditional South Indian tiffin.',
                  'People exploring different millet and heritage-rice varieties.',
                  'Versatile savoury semiya recipes.'],
  'serving': 'Prepare as vegetable semiya, lemon sevai or coconut sevai with vegetables, peanuts, coconut or fresh '
             'herbs.',
  'recipe_ideas': ['Five-Grain Vegetable Semiya: Add seasonal vegetables, onions, curry leaves and mild spices.',
                   'Mixed Millet Lemon Sevai: Toss cooked semiya with lemon juice, turmeric, peanuts and mustard '
                   'seeds.'],
  'preparation': ['First, roast the vermicelli lightly.',
                  'Then, sauté mustard seeds, curry leaves, onions and vegetables.',
                  'Add water and bring it to a boil.',
                  'Finally, add the vermicelli and cook until soft.',
                  'Serve hot!'],
  'storage': 'Store in a cool, dry and hygienic place, away from direct sunlight.',
  'allergen': 'Contains wheat.',
  'net_weight': '200 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Barnyard Millet: Dietary fibre supports digestive regularity; iron contributes to '
                        'haemoglobin formation.',
                        'Foxtail Millet: Plant protein contributes to tissue maintenance; magnesium supports '
                        'muscle/nerve function.',
                        'Kodo Millet: Dietary fibre supports digestive function; phosphorus contributes to '
                        'bone/teeth maintenance.',
                        'Little Millet: Dietary fibre supports bowel regularity; iron contributes to oxygen '
                        'transport.',
                        'Mapillai Samba Rice: Research on the grain has identified phenolic compounds and '
                        'anthocyanins.'],
  'blend_details': [],
  'catalogue_mrp': '₹99',
  'catalogue_net_weight': '200 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These benefits describe the grain ingredients, not measured nutrient levels in the '
                          'finished RR FOODS product. Serving suggestions and recipe ideas are editorial '
                          'suggestions, not manufacturer instructions.'},
 {'number': 12,
  'sku': 'RR-PCB-002',
  'name': 'Multi Millet Muesli',
  'local_name': 'Breakfast Grain, Fruit & Seed Blend',
  'strapline': 'A colourful start to your everyday breakfast.',
  'description': 'Bring together grains, fruit and seeds in a convenient breakfast mix. Enjoy Multi Millet Muesli '
                 'with hot milk, cold milk or yoghurt and customise your bowl with fresh fruit.',
  'ingredients': 'Millet Flour, Corn Grits, Corn Meal, Wheat Flour (Atta), Rice, Rice Flour, Sugar, Rolled Barley, '
                 'Rolled Oats, Raisins, Black Raisins, Candied Papaya and Pumpkin Seeds.',
  'perfect_for': ['Quick breakfast routines.',
                  'People who enjoy grain, fruit and seed combinations.',
                  'Serving with hot milk, cold milk or yoghurt.',
                  'Customisable breakfast bowls.'],
  'serving': 'Serve with hot milk, cold milk or yoghurt. Add banana, apple, seasonal fruit or extra seeds to '
             'customise your bowl.',
  'recipe_ideas': ['Fruit & Muesli Bowl: Combine muesli with chilled milk and sliced banana or apple.',
                   'Yoghurt Muesli Bowl: Layer yoghurt, muesli and fresh fruit in a serving glass.',
                   'Warm Breakfast Bowl: Add warm milk to muesli and allow it to soften before serving.'],
  'preparation': [],
  'storage': None,
  'allergen': 'Contains wheat (also includes barley and oats).',
  'net_weight': '175 g',
  'best_before': '6 months from date of manufacture',
  'nutrition_context': ['A blend of grains: Combines millet flour with corn, wheat, rice, barley and oats for '
                        'variety in the breakfast bowl.',
                        'Fruit ingredients: Raisins, black raisins and candied papaya add fruit-based flavour and '
                        'texture.',
                        'Seed variety: Pumpkin seeds add another plant-based ingredient to the mix.',
                        'Easy breakfast option: A convenient base that can be paired with milk, yoghurt and fresh '
                        'fruit.'],
  'blend_details': [],
  'catalogue_mrp': '₹149',
  'catalogue_net_weight': '175 g',
  'catalogue_best_before': '6 months from date of manufacture',
  'nutrition_disclaimer': 'These notes describe the ingredients, not measured nutrient levels in the finished RR '
                          'FOODS product. Serving suggestions and recipe ideas are editorial suggestions, not '
                          'manufacturer instructions.'},
 {'number': 13,
  'sku': 'RR-PCB-006',
  'name': 'Millet Pasta Sample',
  'local_name': 'Multi Millet Pasta',
  'strapline': 'Traditional millet ingredients in a versatile pasta format.',
  'description': 'A millet-based pasta option using the available Multi Millet Pasta label information.',
  'ingredients': 'Multi Millet Flour (Barnyard Millet, Foxtail Millet, Kodo Millet and Little Millet), Whole Wheat '
                 'Flour, Salt and Tastemaker.',
  'perfect_for': ['Everyday pasta meals.',
                  'Vegetable-based pasta recipes.',
                  'People exploring millet-based food options.'],
  'serving': 'Pair with tomato sauce, herbs, sautéed vegetables or a preferred pasta sauce.',
  'recipe_ideas': ['Vegetable Millet Pasta: Toss prepared pasta with sautéed vegetables and tomato sauce.',
                   'Herb Pasta: Combine with olive oil, garlic, herbs and vegetables.'],
  'preparation': [],
  'storage': None,
  'allergen': 'Contains wheat.',
  'net_weight': '180 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Four millet ingredients: Lists barnyard, foxtail, kodo and little millets.',
                        'Grain variety: Combines different traditional millet varieties in a familiar pasta format.',
                        'Versatile meal option: Can be paired with vegetables and preferred pasta sauces.'],
  'blend_details': [],
  'catalogue_mrp': '₹129',
  'catalogue_net_weight': '180 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These notes describe the ingredients, not measured nutrient levels in the finished RR '
                          'FOODS product. Serving suggestions and recipe ideas are editorial suggestions, not '
                          'manufacturer instructions.'},
 {'number': 14,
  'sku': 'RR-PCB-005',
  'name': 'Beetroot Pasta',
  'local_name': 'Beetroot Millet-Range Pasta',
  'strapline': 'A colourful ingredient for creative pasta meals.',
  'description': 'Bring beetroot into a familiar pasta format. Pair it with vegetables, herbs and your favourite '
                 'sauce to make a colourful meal for everyday lunch or dinner.',
  'ingredients': 'Beetroot, Whole Wheat Flour, Salt and Tastemaker.',
  'perfect_for': ['Colourful lunch and dinner meals.',
                  'People who enjoy vegetable-based pasta.',
                  'Preparing pasta with tomato sauce and fresh vegetables.'],
  'serving': 'Pair with tomato sauce, sautéed vegetables, herbs or a preferred pasta sauce.',
  'recipe_ideas': ['Beetroot Vegetable Pasta: Combine prepared pasta with sautéed vegetables and tomato sauce.',
                   'Beetroot Herb Pasta: Toss with garlic, herbs and olive oil.',
                   'Creamy Beetroot Pasta: Serve with a creamy sauce and sautéed vegetables.'],
  'preparation': [],
  'storage': None,
  'allergen': 'Contains wheat.',
  'net_weight': '180 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Beetroot ingredient: Beetroot contributes naturally occurring plant pigments and '
                        'distinctive vegetable character.',
                        'Everyday meal variety: Offers another way to include a vegetable ingredient in a pasta '
                        'dish.',
                        'Versatile pairing: Works with tomato, herb and vegetable-based sauces.'],
  'blend_details': [],
  'catalogue_mrp': '₹129',
  'catalogue_net_weight': '180 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These notes describe the ingredients, not measured nutrient levels in the finished RR '
                          'FOODS product. Serving suggestions and recipe ideas are editorial suggestions, not '
                          'manufacturer instructions.'},
 {'number': 15,
  'sku': 'RR-BTM-001',
  'name': 'Multi Millet Chapati Mix',
  'local_name': 'Multi Millet Grain Atta',
  'strapline': 'A blend of grains, pulses and seeds for everyday rotis.',
  'description': 'Bring a variety of traditional grains and plant ingredients into homemade chapatis. This '
                 'multi-ingredient atta combines millets, pulses and flaxseeds for versatile everyday cooking.',
  'ingredients': 'Wheat, Finger Millet, Pearl Millet, Kodo Millet, Little Millet, Barnyard Millet, Green Gram, White '
                 'Chickpeas and Flaxseeds.',
  'perfect_for': ['Homemade chapatis and rotis.',
                  'Everyday family meals.',
                  'People interested in combining grains, pulses and seeds.'],
  'serving': 'Serve freshly prepared chapatis with vegetable curry, dal, kurma, chutney or yoghurt.',
  'recipe_ideas': ['Everyday Multi Millet Chapati: Prepare dough with water, rest, roll into discs and cook on hot '
                   'tawa.',
                   'Stuffed Millet Paratha: Use dough to prepare stuffed flatbreads with vegetable filling.'],
  'preparation': [],
  'storage': None,
  'allergen': 'Contains wheat.',
  'net_weight': '500 g',
  'best_before': '12 months from date of manufacture',
  'nutrition_context': ['Millet variety: Combines finger millet, pearl millet, kodo millet, little millet and '
                        'barnyard millet.',
                        'Grains and pulses together: Green gram and white chickpeas add pulse-based ingredients.',
                        'Flaxseed inclusion: Flaxseeds add another plant-based ingredient to the mix.',
                        'Versatile everyday cooking: Prepare chapatis and other flatbread-style meals.'],
  'blend_details': [],
  'catalogue_mrp': '₹129',
  'catalogue_net_weight': '500 g',
  'catalogue_best_before': '12 months from date of manufacture',
  'nutrition_disclaimer': 'These notes describe the ingredients, not measured nutrient levels in the finished RR '
                          'FOODS product. Serving suggestions and recipe ideas are editorial suggestions, not '
                          'manufacturer instructions.'},
 {'number': 16,
  'sku': 'RR-BTM-003',
  'name': 'Idli Podi – Inippu Ellu Idli Podi',
  'local_name': 'Sweet Sesame Idli Podi',
  'strapline': 'A sweet-and-savoury traditional accompaniment.',
  'description': 'A distinctive idli podi made with sesame seeds, urad dal, jaggery and traditional spices. Enjoy '
                 'its sweet, savoury and gently spiced flavour with familiar South Indian tiffin.',
  'ingredients': 'Urad Dal, Jaggery, Sesame Seeds, Dried Red Chillies, Garlic, Curry Leaves, Asafoetida and Salt.',
  'perfect_for': ['Idli and dosa accompaniments.',
                  'Traditional South Indian breakfast and tiffin.',
                  'People who enjoy sweet-and-savoury podi flavours.'],
  'serving': 'Serve with idli or dosa. Mix with sesame oil or ghee to make a flavourful dipping accompaniment.',
  'recipe_ideas': ['Podi Idli: Toss bite-sized idlis with a little sesame oil and Inippu Ellu Idli Podi.',
                   'Podi Dosa: Sprinkle podi over freshly cooked dosa.',
                   'Podi Rice: Mix with warm rice and a little oil or ghee.'],
  'preparation': [],
  'storage': None,
  'allergen': 'Contains sesame.',
  'net_weight': '250 g',
  'best_before': '6 months from date of manufacture',
  'nutrition_context': ['Sesame seed character: Contributes plant-based fats, protein and naturally occurring '
                        'minerals.',
                        'Urad dal ingredient: Contributes pulse-based plant protein.',
                        'Traditional flavour ingredients: Garlic, curry leaves and dried red chillies create savoury '
                        'flavour.',
                        'Jaggery for sweetness: Gives this podi its distinctive sweet note.'],
  'blend_details': [],
  'catalogue_mrp': '₹150',
  'catalogue_net_weight': '250 g',
  'catalogue_best_before': '6 months from date of manufacture',
  'nutrition_disclaimer': 'These notes describe the ingredients, not measured nutrient levels in the finished RR '
                          'FOODS product. Serving suggestions and recipe ideas are editorial suggestions, not '
                          'manufacturer instructions.'},
 {'number': 17,
  'sku': 'RR-BTM-004',
  'name': 'Traditional Tirunelveli-style Idli Podi',
  'local_name': 'Traditional Idli Podi',
  'strapline': 'A classic South Indian tiffin accompaniment.',
  'description': 'Enjoy a traditional-style idli podi prepared with sesame seeds, urad dal and familiar South Indian '
                 'spices. A flavourful accompaniment for idli, dosa and other tiffin favourites.',
  'ingredients': 'Sesame Seeds, Urad Dal, Dried Red Chillies, Garlic, Curry Leaves, Asafoetida and Salt.',
  'perfect_for': ['Idli and dosa.',
                  'Traditional South Indian tiffin.',
                  'People who enjoy a savoury, spiced accompaniment.'],
  'serving': 'Serve with idli or dosa. Mix with sesame oil or ghee to prepare a classic podi dip.',
  'recipe_ideas': ['Podi Idli: Toss bite-sized idlis with sesame oil and idli podi.',
                   'Podi Dosa: Sprinkle podi over freshly cooked dosa.',
                   'Podi Rice: Mix with warm rice and a little sesame oil or ghee.'],
  'preparation': [],
  'storage': None,
  'allergen': 'Contains sesame.',
  'net_weight': '250 g',
  'best_before': '6 months from date of manufacture',
  'nutrition_context': ['Sesame seed ingredient: Contributes plant-based fats, protein and naturally occurring '
                        'minerals.',
                        'Urad dal ingredient: Provides a pulse-based ingredient with naturally occurring plant '
                        'protein.',
                        'Traditional spice blend: Dried red chillies, garlic and curry leaves bring flavour and '
                        'aroma.'],
  'blend_details': [],
  'catalogue_mrp': '₹150',
  'catalogue_net_weight': '250 g',
  'catalogue_best_before': '6 months from date of manufacture',
  'nutrition_disclaimer': 'These notes describe the ingredients, not measured nutrient levels in the finished RR '
                          'FOODS product. Serving suggestions and recipe ideas are editorial suggestions, not '
                          'manufacturer instructions.'},
 {'number': 18,
  'sku': 'RR-BTM-005',
  'name': 'Moringa Leaf Soup Mix',
  'local_name': 'Moringa Soup Mix',
  'strapline': 'A comforting soup with moringa leaves and traditional spices.',
  'description': 'Enjoy a warm, savoury soup made with moringa leaves, lentils and familiar Indian spices. A '
                 'convenient soup mix for a quick break or a light meal.',
  'ingredients': 'Moringa Leaves, Moong Dal, Black Pepper, Cumin, Turmeric, Ginger, Coriander, Masoor Dal and Salt.',
  'perfect_for': ['A warm savoury snack.',
                  'A light meal or soup course.',
                  'People who enjoy moringa and lentil-based preparations.'],
  'serving': 'Serve warm on its own or alongside toast, steamed vegetables or a light meal.',
  'recipe_ideas': ['Classic Moringa Soup: Prepare using packet directions and serve warm.',
                   'Pepper Moringa Soup: Add freshly crushed black pepper and chopped coriander before serving.'],
  'preparation': ['Add 5 g of soup powder to 150 ml of water.',
                  'Stir until dissolved.',
                  'Heat for 2 minutes and serve warm. Tip: Mix with room-temp water first, then heat.'],
  'storage': None,
  'allergen': None,
  'net_weight': '130 g',
  'best_before': '6 months from date of manufacture',
  'nutrition_context': ['Moringa leaf ingredient: Brings a leafy green ingredient traditionally used in Indian '
                        'cooking.',
                        'Lentil ingredients: Moong dal and masoor dal contribute pulse-based ingredients.',
                        'Traditional spices: Black pepper, cumin, turmeric, ginger and coriander add flavour and '
                        'aroma.',
                        'Quick to prepare: A simple soup option that can be prepared with water.'],
  'blend_details': [],
  'catalogue_mrp': '₹159',
  'catalogue_net_weight': '130 g',
  'catalogue_best_before': '6 months from date of manufacture',
  'nutrition_disclaimer': 'These notes describe the ingredients, not measured nutrient levels in the finished RR '
                          'FOODS product. Serving suggestions and recipe ideas are editorial suggestions, not '
                          'manufacturer instructions.'},
 {'number': 19,
  'sku': 'RR-BTM-006',
  'name': 'Soup Base Mix',
  'local_name': 'Vegetable or Chicken Soup Base',
  'strapline': 'A savoury spice-and-pulse base for a comforting soup.',
  'description': 'Prepare a comforting soup with green gram dal and a blend of traditional spices. Use it as a '
                 'convenient base and customise the bowl with cooked vegetables or chicken.',
  'ingredients': 'Green Gram Dal, Cumin, Black Pepper, Turmeric, Ginger, Coriander and Salt.',
  'perfect_for': ['Quick savoury soup preparation.',
                  'Customising soup with vegetables.',
                  'Preparing chicken-based soup.',
                  'A warm starter or light meal.'],
  'serving': 'Add cooked chicken or vegetables as preferred. Serve warm with fresh coriander.',
  'recipe_ideas': ['Vegetable Soup: Prepare soup base, add cooked vegetables and heat until combined.',
                   'Chicken Soup: Prepare soup base, add cooked chicken and heat until combined.'],
  'preparation': ['Add 5 g of soup base to 150 ml of water.',
                  'Stir until dissolved.',
                  'Add cooked chicken or vegetables.',
                  'Heat for 2 minutes and serve warm.'],
  'storage': None,
  'allergen': None,
  'net_weight': '130 g',
  'best_before': '6 months from date of manufacture',
  'nutrition_context': ['Green gram dal ingredient: A pulse that naturally provides plant protein and dietary fibre.',
                        'Traditional spice blend: Cumin, black pepper, turmeric, ginger and coriander build savoury '
                        'flavour.',
                        'Versatile soup base: Can be combined with cooked vegetables or chicken.',
                        'Convenient preparation: A simple base for preparing warm soup at home.'],
  'blend_details': [],
  'catalogue_mrp': '₹159',
  'catalogue_net_weight': '130 g',
  'catalogue_best_before': '6 months from date of manufacture',
  'nutrition_disclaimer': 'These notes describe the ingredients, not measured nutrient levels in the finished RR '
                          'FOODS product. Serving suggestions and recipe ideas are editorial suggestions, not '
                          'manufacturer instructions.'},
 {'number': 20,
  'sku': 'RR-TNF-004',
  'name': 'Karuppu Kavuni + Karuppu Uluthu Kanji Mix',
  'local_name': None,
  'strapline': 'Traditional black rice, pulses, nuts and seeds in one kanji mix.',
  'description': 'A traditional-inspired kanji mix bringing together Black Kavuni Rice, Black Urad Dal, nuts and '
                 'seeds. Prepare it as a warm, comforting food using the cooking directions confirmed on the final '
                 'pack.',
  'ingredients': 'Black Kavuni Rice, Black Urad Dal, Almonds, Cashew Nuts, Pumpkin Seeds, Sunflower Seeds and Flax '
                 'Seeds.',
  'perfect_for': ['People interested in traditional rice-based foods.',
                  'A warm breakfast or meal preparation, subject to pack directions.',
                  'Those who enjoy combinations of grains, pulses, nuts and seeds.'],
  'serving': 'Serve as a warm kanji once prepared according to the final product instructions.',
  'recipe_ideas': [],
  'preparation': [],
  'storage': None,
  'allergen': 'Contains almonds and cashew nuts.',
  'net_weight': '275 g',
  'best_before': '6 months from date of manufacture',
  'nutrition_context': ['Black Kavuni rice: Pigmented traditional rice variety studied for naturally occurring '
                        'phenolic compounds and anthocyanins.',
                        'Black urad dal: Pulse ingredient that naturally contributes plant protein.',
                        'Nuts and seeds: Almonds, cashews, pumpkin seeds, sunflower seeds and flaxseeds.',
                        'Ingredient variety: Combines grains, pulses, nuts and seeds in one convenient mix.'],
  'blend_details': [],
  'catalogue_mrp': '₹349',
  'catalogue_net_weight': '275 g',
  'catalogue_best_before': '6 months from date of manufacture',
  'nutrition_disclaimer': 'These notes describe the ingredients, not measured nutrient levels in the finished RR '
                          'FOODS product. Serving suggestions and recipe ideas are editorial suggestions, not '
                          'manufacturer instructions.'}]

CATALOGUE_COMBO_OFFER = {'title': 'RR FOODS – ₹999 TRADITIONAL GRAINS & EVERYDAY ESSENTIALS COMBO',
 'strapline': 'Seven familiar favourites. One thoughtfully put-together pantry combo.',
 'description': 'Explore a selection of millet-based foods and traditional favourites in one convenient bundle. From '
                'quick meals and everyday cooking to a traditional podi and kanji preparation, this combo brings a '
                'variety of RR Foods products together for the family pantry.',
 'price': '₹999',
 # One pack of each, exactly the 7 lines of the Excel "Combo Offer" sheet. SKUs are the catalogue SKUs (app/seed_data/seed_products.csv);
 # names are the Excel combo-sheet names (column "Combo Product (Bundle Name)"). Two deliberate exceptions, both flagged for the client:
 # "Soup Mix (selected variant)" is shown as Moringa Leaf Soup Mix (the sheet maps it to that product), and "Biotin" is left out of the
 # kanji mix name because the Excel flags it as an unsubstantiated label claim.
 'items': [{'sku': 'RR-MN-005', 'name': 'Multi Millet Instant Noodles', 'pack': '180 g', 'mrp': 129},
           {'sku': 'RR-PCB-006', 'name': 'Multi Millet Pasta', 'pack': '180 g', 'mrp': 129},
           {'sku': 'RR-MV-006', 'name': 'Multi Millet Vermicelli (Semiya)', 'pack': '200 g', 'mrp': 99},
           {'sku': 'RR-BTM-001', 'name': 'Multi Millet Chapati Maavu (Multi Millet Grain Atta)', 'pack': '500 g', 'mrp': 129},
           {'sku': 'RR-BTM-005', 'name': 'Moringa Leaf Soup Mix', 'pack': '130 g', 'mrp': 159},
           {'sku': 'RR-BTM-004', 'name': 'Traditional Tirunelveli Idli Podi', 'pack': '250 g', 'mrp': 150},
           {'sku': 'RR-TNF-004', 'name': 'Karuppu Kavuni + Karuppu Uluthu Kanji Mix', 'pack': '275 g', 'mrp': 349}]}
for _number in (5, 11, 13, 15, 17, 18, 20):  # not 19 (Soup Base Mix): it is not in the combo
    PRODUCT_CATALOGUE[_number - 1]["combo_offer"] = CATALOGUE_COMBO_OFFER


def _normalise(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def catalogue_for_product(product):
    """The catalogue entry for a store product: by SKU first, then by product name."""
    sku = (getattr(product, "sku", "") or "").strip().upper()
    for item in PRODUCT_CATALOGUE:
        if item["sku"] == sku:
            return item
    name = _normalise(getattr(product, "name", ""))
    for item in PRODUCT_CATALOGUE:
        if name and name == _normalise(item["name"]):
            return item
    return None
